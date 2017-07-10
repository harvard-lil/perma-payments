from datetime import datetime
import random
from uuid import uuid4
import hashlib
import hmac
import base64

from django.conf import settings
from django.shortcuts import render

from .constants import *

def index(request):
    return render(request, 'generic.html', {'heading': "perma-payments",
                                            'message': "a window to CyberSource Secure Acceptance Web/Mobile"})

def payment_form(request):
    signed_fields = {
        'access_key': settings.CS_ACCESS_KEY,
        'amount': get_price(),
        'currency': 'USD',
        'locale': 'en-us',
        'payment_method': 'card',
        'profile_id': settings.CS_PROFILE_ID,
        # 'recurring_amount': get_price(),
        # 'recurring_frequency': 'monthly',
        'reference_number': generate_reference_number(),
        'signed_date_time': datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        'signed_field_names': '',
        'transaction_type': 'sale',
        # 'transaction_type': 'authorization,create_payment_token',
        'transaction_uuid': str(uuid4()),
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
    context['heading'] = "Payment Form"
    context['post_to_url'] = CS_PAYMENT_URL[settings.CS_MODE]
    return render(request, 'payment-form.html', context)

def get_price():
    """
    This should return the correct price for a customer.
    """
    return "1.00"

def generate_reference_number():
    """

    """
    # Based on GUID generation in Perma
    # only try 100 attempts at finding an unused GUID
    # (100 attempts should never be necessary, since we'll expand the keyspace long before
    # there are frequent collisions)
    guid_character_set = "0123456789"
    reference_number_prefix = "PERMA"
    for i in range(100):
        # Generate an 8-character random string like "912768"
        guid = ''.join(random.choice(guid_character_set) for _ in range(8))

        # apply standard formatting (hyphens)
        guid = get_canonical_guid(guid)

        # TODO: make transaction model
        # if not match and not Transaction.objects.filter(guid=guid).exists():
        #     break
        break
    else:
        raise Exception("No valid GUID found in 100 attempts.")
    return "{}-{}".format(reference_number_prefix, guid)

def get_canonical_guid(guid):
    """
    Given a GUID, return the canonical version, with hyphens every 4 chars.
    So "12345678" becomes "1234-5678".
    """

    # split guid into 4-char chunks, starting from the end
    guid_parts = [guid[max(i - 4, 0):i] for i in
                  range(len(guid), 0, -4)]

    # stick together parts with '-'
    return "-".join(reversed(guid_parts))

def data_to_string(data):
    return ','.join('{}={}'.format(key, data[key]) for key in sorted(data))

def sign_data(data_string):
    """
    Sign with HMAC sha256 and base64 encode
    """
    message = bytes(data_string, 'utf-8')
    secret = bytes(settings.CS_SECRET_KEY, 'utf-8')
    hash = hmac.new(secret, message, hashlib.sha256)
    return base64.b64encode(hash.digest())
