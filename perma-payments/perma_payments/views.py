import csv
from datetime import datetime
import io

from django.conf import settings
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
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
        data = verify_perma_transmission(request.POST, ('registrar',
                                                        'amount',
                                                        'recurring_amount',
                                                        'recurring_frequency',
                                                        'recurring_start_date'))
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must not already have a standing subscription.
    if SubscriptionAgreement.registrar_standing_subscription(data['registrar']):
        return render(request, 'generic.html', {'heading': "Good News!",
                                                'message': "You already have a subscription to Perma.cc.<br>" +
                                                           "If you believe you have reached this page in error, please contact us at <a href='mailto:info@perma.cc?subject=Our%20Subscription'>info@perma.cc</a>."})

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
        data = verify_perma_transmission(request.POST, ('registrar',))
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must have a subscription that can be updated.
    try:
        sa = SubscriptionAgreement.registrar_standing_subscription(data['registrar'])
        assert sa and sa.can_be_altered()
    except AssertionError:
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Update Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:info@perma.cc?subject=Our%20Subscription'>info@perma.cc</a>."})

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
        logger.warning('Invalid POST from Perma.cc subscribe form: {}'.format(e))
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


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters(*SENSITIVE_POST_PARAMETERS)
def cybersource_callback(request):
    """
    In dev, curl http://192.168.99.100/cybersource-callback/ -X POST -d '@/Users/rcremona/code/perma-payments/sample_response.txt'
    """
    data = verify_cybersource_transmission(request.POST, (
        'req_transaction_uuid',
        'decision',
        'reason_code',
        'message'
    ))

    related_request = OutgoingTransaction.objects.get(transaction_uuid=data['req_transaction_uuid'])
    subscription_agreement = related_request.subscription_agreement
    registrar = related_request.registrar
    decision = data['decision']
    reason_code = data['reason_code']
    message = data['message']
    non_sensitive_params = {k: v for (k, v) in request.POST.items() if k not in SENSITIVE_POST_PARAMETERS}

    if isinstance(related_request, UpdateRequest):
        Response.save_new_w_encryped_full_response(
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

        Response.save_new_w_encryped_full_response(
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

        if decision == 'ACCEPT':
            # Successful transaction. Reason codes 100 and 110.
            subscription_agreement.status = 'Current'
            subscription_agreement.save()
            logger.info("Subscription request for registrar {} (subscription request {}) accepted.".format(registrar, related_request.pk))
        elif decision == 'REVIEW':
            # Authorization was declined; however, the capture may still be possible.
            # Review payment details. See reason codes 200, 201, 230, and 520.
            # (for now, we are treating this like 'ACCEPT', until we see an example in real life and can improve the logic)
            subscription_agreement.status = 'Current'
            subscription_agreement.save()
            logger.error("Subscription request for registrar {} (subscription request {}) flagged for review by CyberSource. Please investigate ASAP. Redacted response: {}".format(registrar, related_request.pk, non_sensitive_params))
        elif decision == 'CANCEL':
            # The customer did not accept the service fee conditions,
            # or the customer cancelled the transaction.
            subscription_agreement.status = 'Aborted'
            subscription_agreement.save()
            logger.info("Subscription request {} aborted by registrar {}.".format(related_request.pk, registrar))
        elif decision == 'DECLINE':
            # Transaction was declined.See reason codes 102, 200, 202, 203,
            # 204, 205, 207, 208, 210, 211, 221, 222, 230, 231, 232, 233,
            # 234, 236, 240, 475, 476, and 481.
            subscription_agreement.status = 'Rejected'
            subscription_agreement.save()
            logger.warning("Subscription request for registrar {} (subscription request {}) declined by CyberSource. Redacted response: {}".format(registrar, related_request.pk, non_sensitive_params))
        elif decision == 'ERROR':
            # Access denied, page not found, or internal server error.
            # See reason codes 102, 104, 150, 151 and 152.
            subscription_agreement.status = 'Rejected'
            subscription_agreement.save()
            logger.error("Error submitting subscription request {} to CyberSource for registrar {}. Redacted reponse: {}".format(related_request.pk, registrar, non_sensitive_params))
        else:
            logger.error("Unexpected decision from CyberSource regarding subscription request {} for registrar {}. Please investigate ASAP. Redacted reponse: {}".format(related_request.pk, registrar, non_sensitive_params))

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
        data = verify_perma_transmission(request.POST, ('registrar',))
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

    # Once we actually cancel the subscription in the Business Center,
    # whatever method we are using to regularly update the subscription status
    # (manual csv, reporting api, etc.) will update the payment token status to "cancelled"

    # We're going to need something to send us regular emails about subscriptions with cancellation_requested=True,
    # but status = anything but 'cancelled'...
    """
    try:
        data = verify_perma_transmission(request.POST, ('registrar',))
    except InvalidTransmissionException:
        return bad_request(request)

    registrar = data['registrar']

    # The user must have a subscription that can be cancelled.
    try:
        sa = SubscriptionAgreement.registrar_standing_subscription(registrar)
        assert sa and sa.can_be_altered()
    except AssertionError:
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Cancellation Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:info@perma.cc?subject=Our%20Subscription'>info@perma.cc</a>."})

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
    sa.save()
    return redirect(settings.PERMA_SUBSCRIPTION_CANCELLED_URL)


@require_http_methods(["POST"])
def update_statuses(request):
    csv_file = request.FILES['csv_file']
    for i in range(4):
        csv_file.readline()
    reader = csv.DictReader(io.StringIO(csv_file.read().decode('utf-8')))
    for row in reader:
        try:
            sa = SubscriptionAgreement.objects.filter(subscription_request__reference_number=row['Merchant Reference Code']).get()
        except ObjectDoesNotExist:
            logger.error("CyberSource reports a subscription {}: no corresponding record found".format(row['Merchant Reference Code']))
            if settings.RAISE_IF_SUBSCRIPTION_NOT_FOUND:
                raise
            continue
        except SubscriptionAgreement.MultipleObjectsReturned:
            logger.error("Multiple subscription requests associated with {}.".format(row['Merchant Reference Code']))
            if settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND:
                raise
            continue

        sa.status = row['Status']
        sa.save()
        logger.info("Updated subscription status for {} to {}".format(row['Merchant Reference Code'], row['Status']))

    return render(request, 'generic.html', {'heading': "Statuses Updated",
                                            'message': "Check the application log for details."})
