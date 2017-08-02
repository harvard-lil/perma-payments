from werkzeug.security import safe_str_cmp

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .constants import *
from .custom_errors import bad_request
from .models import *
from .security import data_to_string, sign_data, encrypt_for_storage

import logging
logger = logging.getLogger(__name__)


def index(request):
    return render(request, 'generic.html', {'heading': "perma-payments",
                                            'message': "a window to CyberSource Secure Acceptance Web/Mobile"})


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('signature')
def subscribe(request):
    """
    Processes user-initiated subscription requests from Perma.cc;
    Redirects user to CyberSource for payment.
    """
    try:
        data = {
            'registrar': request.POST.__getitem__('registrar'),
            'amount': request.POST.__getitem__('amount'),
            'recurring_amount': request.POST.__getitem__('recurring_amount'),
            'recurring_frequency': request.POST.__getitem__('recurring_frequency')
        }
    except KeyError as e:
        logger.warning('Incomplete POST from Perma.cc subscribe form: missing {}'.format(e))
        return bad_request(request)

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


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters(
    'payment_token'
    'req_access_key',
    'req_bill_to_address_city'
    'req_bill_to_address_country'
    'req_bill_to_address_line1'
    'req_bill_to_address_postal_code'
    'req_bill_to_address_state'
    'req_bill_to_email'
    'req_bill_to_forename'
    'req_bill_to_surname'
    'req_card_expiry_date'
    'req_card_number'
    'req_profile_id',
    'signature'
)
def cybersource_callback(request):
    """
    In dev, curl http://192.168.99.100/cybersource-callback/ -X POST -d '@/Users/rcremona/code/perma-payments/sample_response.txt'
    """
    try:
        signature = request.POST.__getitem__('signature')
        signed_field_names = request.POST.__getitem__('signed_field_names')
        signed_fields = {}
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
        encryption_key_id=settings.STORAGE_SECRET_KEY['id'],
        full_response=encrypt_for_storage(
            bytes(str(request.POST.dict()), 'utf-8'),
            # use the SubscriptionRequest pk as the nonce, to ensure uniqueness
            (sub_req.pk).to_bytes(24, byteorder='big')
        )
    )
    sub_resp.save()

    # TODO
    # finally, take an appropriate action

    return render(request, 'generic.html', {'heading': 'CyberSource Callback', 'message': 'Message Received'})


def perma_spoof(request):
    """
    This logic will live in Perma; here now for simplicity
    """
    context = {
        'subscribe_url': reverse('subscribe')
    }
    return render(request, 'perma-spoof.html', context)
