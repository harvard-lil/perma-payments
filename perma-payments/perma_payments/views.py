from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
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
    return render(request, 'generic.html', {'heading': "perma-payments",
                                            'message': "a window to CyberSource Secure Acceptance Web/Mobile"})


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
                                                        'recurring_frequency'))
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must not already have a current subscription.
    if settings.PREVENT_MULTIPLE_SUBSCRIPTIONS and SubscriptionAgreement.registrar_has_current(data['registrar']):
        return render(request, 'generic.html', {'heading': "Good News!",
                                                'message': "You already have an active subscription to Perma.cc, and your payments are current.<br>" +
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
                recurring_frequency=data['recurring_frequency']
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
        sa = SubscriptionAgreement.get_registrar_latest(data['registrar'])
        s_request = sa.subscription_request
        s_response = s_request.subscription_request_response
        assert sa.can_be_updated()
    except (ObjectDoesNotExist, AssertionError):
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Update Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:info@perma.cc?subject=Our%20Subscription'>info@perma.cc</a>."})

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
def current(request):
    """
    Returns whether a registrar has a paid-up subscription
    """
    try:
        data = verify_perma_transmission(request.POST, ('registrar',))
    except InvalidTransmissionException:
        return bad_request(request)
    response = {
        'registrar': data['registrar'],
        'current': SubscriptionAgreement.registrar_has_current(data['registrar']),
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
        sa = SubscriptionAgreement.get_registrar_latest(registrar)
        assert sa.can_be_cancelled()
    except (ObjectDoesNotExist, AssertionError):
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
    # URL should be in the config, rather than built, when this logic is in Perma
    return redirect('perma_spoof_after_cancellation')


def update_statuses(request):
    pass


def perma_spoof(request):
    """
    This logic will live in Perma; here now for simplicity
    """
    common = {
        'recurring_frequency': "monthly",
        'registrar': "2",
        'timestamp': datetime.utcnow().timestamp()
    }
    bronze = {
        'amount': "2.00",
        'recurring_amount': "2.00",
    }
    silver = {
        'amount': "4.00",
        'recurring_amount': "4.00",
    }
    gold = {
        'amount': "6.00",
        'recurring_amount': "6.00",
    }
    bronze.update(common)
    silver.update(common)
    gold.update(common)
    context = {
        'subscribe_url': reverse('subscribe'),
        'data_bronze': prep_for_perma_payments(bronze),
        'data_silver': prep_for_perma_payments(silver),
        'data_gold': prep_for_perma_payments(gold)
    }
    return render(request, 'perma-spoof.html', context)


def perma_spoof_is_current(request):
    """
    This logic will live in Perma; here now for simplicity.

    In Perma, this won't be a view/route: it will be an api call,
    made before each capture request associated with the registrar.
    """
    import requests
    data = {
        'timestamp': datetime.utcnow().timestamp(),
        'registrar': "1"
    }
    # URL should be in the config, rather than built, when this logic is in Perma
    url = '{}://{}{}'.format(request.scheme, request.get_host(), reverse('current'))
    r = requests.post(url, data={'encrypted_data': prep_for_perma_payments(data)})

    if r.status_code != 200:
        logger.error('Communication with perma-payments failed. Status: {}'.format(r.status_code))
        # Give people the benefit of the doubt? Put a boolean in config when this logic is in Perma
        return JsonResponse({'registrar': data['registrar'], 'current': True })

    post_data = verify_perma_payments_transmission(r.json(), ('registrar', 'current'))
    return JsonResponse({'registrar': post_data['registrar'], 'current': post_data['current']})


def perma_spoof_cancel_confirm(request):
    """
    This logic will live in Perma; here now for simplicity
    """
    context = {
        'cancel_url': reverse('cancel_request'),
        'data': prep_for_perma_payments({
            'registrar': "1",
            'timestamp': datetime.utcnow().timestamp()
        })
    }
    return render(request, 'perma-spoof-cancel-confirm.html', context)


def perma_spoof_after_cancellation(request):
    return render(request, 'perma-spoof-cancelled.html', {})


def perma_spoof_update_payment(request):
    """
    This logic will live in Perma; here now for simplicity
    """
    context = {
        'update_url': reverse('update'),
        'data': prep_for_perma_payments({
            'registrar': "1",
            'timestamp': datetime.utcnow().timestamp()
        })
    }
    return render(request, 'perma-spoof-update-payment.html', context)
