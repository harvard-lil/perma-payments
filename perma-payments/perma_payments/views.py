from collections import OrderedDict
from datetime import datetime
from werkzeug.security import safe_str_cmp

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .constants import *
from .custom_errors import bad_request
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
    signed_fields = {
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
        'signed_field_names': '',
        'transaction_type': s_request.transaction_type,
        'transaction_uuid': s_request.transaction_uuid,
        'unsigned_field_names': '',

        # billing infomation
        'bill_to_forename': CS_TEST_CUSTOMER['first_name'],
        'bill_to_surname': CS_TEST_CUSTOMER['last_name'],
        'bill_to_email': CS_TEST_CUSTOMER['email'],
        'bill_to_address_line1': CS_TEST_CUSTOMER['street1'],
        'bill_to_address_city': CS_TEST_CUSTOMER['city'],
        'bill_to_address_state': CS_TEST_CUSTOMER['state'],
        'bill_to_address_postal_code': CS_TEST_CUSTOMER['postal_code'],
        'bill_to_address_country': CS_TEST_CUSTOMER['country'],
    }
    unsigned_fields = {}
    unsigned_fields.update(CS_TEST_CARD['visa'])
    signed_fields['signed_field_names'] = ','.join(sorted(signed_fields))
    signed_fields['unsigned_field_names'] = ','.join(sorted(unsigned_fields))
    data_to_sign = data_to_string(signed_fields)
    context = {}
    context.update(signed_fields)
    context.update(unsigned_fields)
    context['signature'] = sign_data(data_to_sign)
    context['heading'] = "Redirecting"
    context['post_to_url'] = CS_PAYMENT_URL[settings.CS_MODE]
    logger.info("Subscription request received for registrar {}".format(data['registrar']))
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
    try:
        signature = request.POST.__getitem__('signature')
        signed_field_names = request.POST.__getitem__('signed_field_names')
        signed_fields = OrderedDict()
        for field in signed_field_names.split(','):
            signed_fields[field] = request.POST.__getitem__(field)
    except KeyError as e:
        logger.warning('Incomplete POST to CyberSource callback route: missing {}'.format(e))
        return bad_request(request)

    data_to_sign = data_to_string(signed_fields, sort=False)
    if not safe_str_cmp(signature, sign_data(data_to_sign)):
        logger.warning('Data with invalid signature POSTed to CyberSource callback route')
        return bad_request(request)

    sub_req = SubscriptionRequest.objects.get(
        reference_number=request.POST.__getitem__('req_reference_number'),
        transaction_uuid=request.POST.__getitem__('req_transaction_uuid')
    )
    sub_resp = SubscriptionRequestResponse(
        subscription_request=sub_req,
        decision=request.POST.__getitem__('decision'),
        reason_code=request.POST.__getitem__('reason_code'),
        message=request.POST.__getitem__('message'),
        payment_token=request.POST.get('payment_token', ''),
        encryption_key_id=settings.STORAGE_ENCRYPTION_KEYS['id'],
        full_response=encrypt_for_storage(
            bytes(str(request.POST.dict()), 'utf-8'),
            # use the SubscriptionRequest pk as the nonce, to ensure uniqueness
            (sub_req.pk).to_bytes(24, byteorder='big')
        )
    )
    sub_resp.save()

    decision = sub_resp.decision
    agreement = sub_req.subscription_agreement
    non_sensitive_params = {k: v for (k, v) in request.POST.items() if k not in SENSITIVE_POST_PARAMETERS}
    if decision == 'ACCEPT':
        # Successful transaction. Reason codes 100 and 110.
        agreement.status = 'Current'
        agreement.save()
        logger.info("Subscription request for registrar {} (subscription request {}) accepted.".format(agreement.registrar, sub_req.pk))
    elif decision == 'REVIEW':
        # Authorization was declined; however, the capture may still be possible.
        # Review payment details. See reason codes 200, 201, 230, and 520.
        # (for now, we are treating this like 'ACCEPT', until we see an example in real life and can improve the logic)
        agreement.status = 'Current'
        agreement.save()
        logger.error("Subscription request for registrar {} (subscription request {}) flagged for review by CyberSource. Please investigate ASAP. Redacted response: {}".format(agreement.registrar, sub_req.pk, non_sensitive_params))
    elif decision == 'CANCEL':
        # The customer did not accept the service fee conditions,
        # or the customer cancelled the transaction.
        agreement.status = 'Aborted'
        agreement.save()
        logger.info("Subscription request {} aborted by registrar {}.".format(sub_req.pk, agreement.registrar))
    elif decision == 'DECLINE':
        # Transaction was declined.See reason codes 102, 200, 202, 203,
        # 204, 205, 207, 208, 210, 211, 221, 222, 230, 231, 232, 233,
        # 234, 236, 240, 475, 476, and 481.
        agreement.status = 'Rejected'
        agreement.save()
        logger.warning("Subscription request for registrar {} (subscription request {}) declined by CyberSource. Redacted response: {}".format(agreement.registrar, sub_req.pk, non_sensitive_params))
    elif decision == 'ERROR':
        # Access denied, page not found, or internal server error.
        # See reason codes 102, 104, 150, 151 and 152.
        agreement.status = 'Rejected'
        agreement.save()
        logger.error("Error submitting subscription request {} to CyberSource for registrar {}. Redacted reponse: {}".format(sub_req.pk, agreement.registrar, non_sensitive_params))
    else:
        logger.error("Unexpected decision from CyberSource regarding subscription request {} for registrar {}. Please investigate ASAP. Redacted reponse: {}".format(sub_req.pk, agreement.registrar, non_sensitive_params))

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


def perma_spoof(request):
    """
    This logic will live in Perma; here now for simplicity
    """
    common = {
        'recurring_frequency': "monthly",
        'registrar': "1",
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
