import csv
from datetime import datetime
from functools import wraps
import io

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, ObjectDoesNotExist, MultipleObjectsReturned, PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.decorators import available_attrs
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .constants import *
from .custom_errors import bad_request
from .email import send_admin_email
from .models import *
from .security import *

import logging
logger = logging.getLogger(__name__)

#
# UTILS
#

FIELDS_REQUIRED_FROM_PERMA = {
    'subscribe': [
        'registrar',
        'amount',
        'recurring_amount',
        'recurring_frequency',
        'recurring_start_date'
    ],
    'update': [
        'registrar'
    ],
    'subscription': [
        'registrar'
    ],
    'cancel_request': [
        'registrar'
    ]
}

FIELDS_REQUIRED_FOR_CYBERSOURCE = {
    'subscribe': [
        'access_key',
        'amount',
        'currency',
        'locale',
        'payment_method',
        'profile_id',
        'recurring_amount',
        'recurring_frequency',
        'recurring_start_date',
        'reference_number',
        'signed_date_time',
        'transaction_type',
        'transaction_uuid'
    ],
    'update': [
        'access_key',
        'allow_payment_token_update',
        'locale',
        'payment_method',
        'payment_token',
        'profile_id',
        'reference_number',
        'signed_date_time',
        'transaction_type',
        'transaction_uuid'
    ]
}

FIELDS_REQUIRED_FROM_CYBERSOURCE = {
    'cybersource_callback': [
        'req_transaction_uuid',
        'decision',
        'reason_code',
        'message'
    ]
}

SENSITIVE_POST_PARAMETERS = [
    'payment_token',
    'req_access_key',
    'req_bill_to_address_city',
    'req_bill_to_address_country',
    'req_bill_to_address_line1',
    'req_bill_to_address_postal_code',
    'req_bill_to_address_state',
    'req_bill_to_email',
    'req_bill_to_forename',
    'req_bill_to_surname',
    'req_card_expiry_date',
    'req_card_number',
    'req_payment_token',
    'req_profile_id',
    'signature'
]


def redact(post):
    return {k: v for (k, v) in post.items() if k not in SENSITIVE_POST_PARAMETERS}


def skip_lines(csv_file, lines):
    """
    Given a file object, advances the read/write head <lines> number of lines.
    Useful for skipping over undesired lines of a file before processing.
    Returns None.
    """
    for i in range(lines):
        csv_file.readline()


def in_mem_csv_to_dict_reader(csv_file):
    """
    A POSTed file is processed by Django and made available as an InMemoryUploadedFile.
    InMemoryUploadedFiles lack the necessary methods to pass them to a csv reader in the normal way.
    This is a work around.
    https://docs.djangoproject.com/en/1.11/ref/files/uploads/
    """
    return csv.DictReader(io.StringIO(csv_file.read().decode('utf-8')))


def user_passes_test_or_403(test_func):
    """
    Decorator for views that checks that the user passes the given test,
    raising PermissionDenied if not. Based on Django's user_passes_test.
    The test should be a callable that takes the user object and
    returns True if the user passes.
    """
    def decorator(view_func):
        @login_required()
        @wraps(view_func, assigned=available_attrs(view_func))
        def _wrapped_view(request, *args, **kwargs):
            if not test_func(request.user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


#
# VIEWS
#

@require_http_methods(["GET"])
def index(request):
    return render(request, 'generic.html', {'heading': "Perma Payments",
                                            'message': "A window to CyberSource Secure Acceptance Web/Mobile"})


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def subscribe(request):
    """
    Processes user-initiated subscription requests from Perma.cc;
    Redirects user to CyberSource for payment.
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['subscribe'])
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must not already have a standing subscription.
    if SubscriptionAgreement.registrar_standing_subscription(data['registrar']):
        return render(request, 'generic.html', {'heading': "Good News!",
                                                'message': "You already have a subscription to Perma.cc.<br>" +
                                                           "If you believe you have reached this page in error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})

    # The subscription request fields must each be valid.
    try:
        with transaction.atomic():
            s_agreement = SubscriptionAgreement(
                registrar=data['registrar'],
                status='Pending'
            )
            s_agreement.full_clean()
            s_agreement.save()
            s_request = SubscriptionRequest(
                subscription_agreement=s_agreement,
                amount=data['amount'],
                recurring_amount=data['recurring_amount'],
                recurring_frequency=data['recurring_frequency'],
                recurring_start_date=data['recurring_start_date']
            )
            s_request.full_clean()
            s_request.save()
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc subscribe form: {}'.format(e))
        return bad_request(request)

    # If all that worked, we can finally bounce the user to CyberSource.
    context = {
        'post_to_url': CS_PAYMENT_URL[settings.CS_MODE],
        'fields_to_post': prep_for_cybersource({
            'access_key': settings.CS_ACCESS_KEY,
            'amount': s_request.amount,
            'currency': s_request.currency,
            'locale': s_request.locale,
            'payment_method': s_request.payment_method,
            'profile_id': settings.CS_PROFILE_ID,
            'recurring_amount': s_request.recurring_amount,
            'recurring_frequency': s_request.recurring_frequency,
            'recurring_start_date': s_request.get_formatted_start_date(),
            'reference_number': s_request.reference_number,
            'signed_date_time': s_request.get_formatted_datetime(),
            'transaction_type': s_request.transaction_type,
            'transaction_uuid': s_request.transaction_uuid,
        })
    }
    logger.info("Subscription request received for registrar {}".format(data['registrar']))
    return render(request, 'redirect.html', context)


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def update(request):
    """
    Processes user-initiated requests from Perma.cc;
    Redirects user to CyberSource for payment.
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['update'])
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must have a subscription that can be updated.
    sa = SubscriptionAgreement.registrar_standing_subscription(data['registrar'])
    if not sa or not sa.can_be_altered():
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Update Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})

    s_request = sa.subscription_request
    s_response = s_request.subscription_request_response

    # The update request fields must each be valid.
    try:
        u_request = UpdateRequest(
            subscription_agreement=sa,
        )
        u_request.full_clean()
        u_request.save()
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc update form: {}'.format(e))
        return bad_request(request)

    # Bounce the user to CyberSource.
    context = {
        'post_to_url': CS_TOKEN_UPDATE_URL[settings.CS_MODE],
        'fields_to_post': prep_for_cybersource({
            'access_key': settings.CS_ACCESS_KEY,
            'allow_payment_token_update': 'true',
            'locale': s_request.locale,
            'payment_method': s_request.payment_method,
            'payment_token': s_response.payment_token,
            'profile_id': settings.CS_PROFILE_ID,
            'reference_number': s_request.reference_number,
            'signed_date_time': u_request.get_formatted_datetime(),
            'transaction_type': u_request.transaction_type,
            'transaction_uuid': u_request.transaction_uuid,
        })
    }
    logger.info("Update payment information request received for registrar {}".format(data['registrar']))
    return render(request, 'redirect.html', context)


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters(*SENSITIVE_POST_PARAMETERS)
def cybersource_callback(request):
    """
    In dev, curl http://192.168.99.100/cybersource-callback/ -X POST -d '@/Users/rcremona/code/perma-payments/sample_response.txt'
    """
    try:
        data = process_cybersource_transmission(request.POST, FIELDS_REQUIRED_FROM_CYBERSOURCE['cybersource_callback'])
    except InvalidTransmissionException:
        return bad_request(request)

    related_request = OutgoingTransaction.objects.get(transaction_uuid=data['req_transaction_uuid'])
    decision = data['decision']
    reason_code = data['reason_code']
    message = data['message']

    if isinstance(related_request, UpdateRequest):
        Response.save_new_with_encrypted_full_response(
            UpdateRequestResponse,
            request.POST,
            {
                'related_request': related_request,
                'decision': decision,
                'reason_code': reason_code,
                'message': message,
            }
        )

    elif isinstance(related_request, SubscriptionRequest):
        payment_token = request.POST.get('payment_token', '')

        # Perma-Payments does not support 16-digit format-preserving Payment Tokens.
        # See docstring for SubscriptionAgreement model for details.
        if len(payment_token) == 16:
            logger.error("16-digit Payment Token received in response to subscription request {}. Not supported by Perma-Payments! Investigate ASAP.".format(related_request.pk))

        Response.save_new_with_encrypted_full_response(
            SubscriptionRequestResponse,
            request.POST,
            {
                'related_request': related_request,
                'decision': decision,
                'reason_code': reason_code,
                'message': message,
                'payment_token': payment_token,
            }
        )
        related_request.subscription_agreement.update_status_after_cs_decision(decision, {k: v for (k, v) in request.POST.items() if k not in SENSITIVE_POST_PARAMETERS})

    else:
        raise NotImplementedError("Can't handle a response of type {}, returned in reponse to outgoing transaction {}".format(type(related_request), related_request.pk))

    return render(request, 'generic.html', {'heading': 'CyberSource Callback', 'message': 'OK'})


@csrf_exempt
@require_http_methods(["POST"])
def subscription(request):
    """
    Returns a simplified version of a registrar's subscription status,
    as needed for making decisions in Perma.
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['subscription'])
    except InvalidTransmissionException:
        return bad_request(request)

    standing_subscription = SubscriptionAgreement.registrar_standing_subscription(data['registrar'])
    if not standing_subscription:
        subscription = None
    else:
        subscription = {
            'rate': standing_subscription.subscription_request.recurring_amount,
            'frequency': standing_subscription.subscription_request.recurring_frequency
        }

        if standing_subscription.cancellation_requested:
            subscription['status'] = 'Cancellation Requested'
        else:
            subscription['status'] = standing_subscription.status

    response = {
        'registrar': data['registrar'],
        'subscription': subscription,
        'timestamp': datetime.utcnow().timestamp()
    }
    return JsonResponse({'encrypted_data': prep_for_perma(response).decode('ascii')})


@csrf_exempt
@require_http_methods(["POST"])
def cancel_request(request):
    """
    Records a cancellation request from Perma.cc
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['cancel_request'])
    except InvalidTransmissionException:
        return bad_request(request)

    registrar = data['registrar']

    # The user must have a subscription that can be cancelled.
    sa = SubscriptionAgreement.registrar_standing_subscription(registrar)
    if not sa or not sa.can_be_altered():
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Cancellation Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})

    context = {
        'registrar': registrar,
        'search_url': CS_SUBSCRIPTION_SEARCH_URL[settings.CS_MODE],
        'perma_url': settings.PERMA_URL,
        'registrar_detail_path': settings.REGISTRAR_DETAIL_PATH,
        'registrar_users_path': settings.REGISTRAR_USERS_PATH,
        'merchant_reference_number': sa.subscription_request.reference_number
    }
    logger.info("Cancellation request received from registrar {} for {}".format(registrar, context['merchant_reference_number']))
    send_admin_email('ACTION REQUIRED: cancellation request received', settings.DEFAULT_FROM_EMAIL, request, template="email/cancel.txt", context=context)
    sa.cancellation_requested = True
    sa.save(update_fields=['cancellation_requested'])
    return redirect(settings.PERMA_SUBSCRIPTION_CANCELLED_REDIRECT_URL)


@user_passes_test_or_403(lambda user: user.is_staff)
@require_http_methods(["POST"])
def update_statuses(request):
    csv_file = request.FILES['csv_file']
    skip_lines(csv_file, 4)
    for row in in_mem_csv_to_dict_reader(csv_file):
        reference = row['Merchant Reference Code']
        status = row['Status']
        try:
            sa = SubscriptionAgreement.objects.filter(subscription_request__reference_number=reference).get()
        except ObjectDoesNotExist:
            logger.error("CyberSource reports a subscription {}: no corresponding record found".format(reference))
            if settings.RAISE_IF_SUBSCRIPTION_NOT_FOUND:
                raise
            continue
        except MultipleObjectsReturned:
            logger.error("Multiple subscription requests associated with {}.".format(reference))
            if settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND:
                raise
            continue

        sa.status = status
        sa.save(update_fields=['status'])
        logger.info("Updated subscription status for {} to {}".format(reference, status))

    return render(request, 'generic.html', {'heading': "Statuses Updated",
                                            'message': "Check the application log for details."})
