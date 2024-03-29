import base64
from collections import OrderedDict
from collections.abc import Mapping
from datetime import timedelta, datetime
import hashlib
import hmac
import json
from nacl import encoding
from nacl.public import SealedBox, Box, PrivateKey, PublicKey
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.debug import sensitive_variables

import logging
logger = logging.getLogger(__name__)

#
# Classes
#


class InvalidTransmissionException(Exception):
    pass


class AlphaNumericValidator(object):
    """
    Password validator, adapted from https://djangosnippets.org/snippets/2551/
    """

    @sensitive_variables()
    def validate(self, password, user=None):
        contains_number = contains_letter = False
        for char in password:
            if not contains_number:
                if char in string.digits:
                    contains_number = True
            if not contains_letter:
                if char in string.ascii_letters:
                    contains_letter = True
            if contains_number and contains_letter:
                break

        if not contains_number or not contains_letter:
            raise ValidationError("This password does not include at least \
                                   one letter and at least one number.")

    def get_help_text(self):
        return "Your password must include at least \
                one letter and at least one number."

#
# Functions
#

# Communicate with CyberSource

@sensitive_variables()
def prep_for_cybersource(signed_fields, unsigned_fields={}):
    """
    Takes a dict of fields to sign, and optionally a dict of fields not to sign.
    Creates the appropriate signature, adds some required administrative fields,
    and packages everything up, returning a dict of data to POST to CyberSource
    via form inputs. (e.g. <input type="hidden" name="KEY" value="VALUE"> for KEY,VALUE in returned_dict)

    Note: if additional fields are POSTed, or if any of these fields fail to be POSTed,
    CyberSource will reject the communication's signature and return 403 Forbidden.
    """
    signed_fields = dict(
        signed_fields,
        unsigned_field_names=','.join(sorted(unsigned_fields)),
        signed_field_names=','.join(sorted(list(signed_fields) + ['signed_field_names', 'unsigned_field_names']))
    )
    to_post = {}
    to_post.update(signed_fields)
    to_post.update(unsigned_fields)
    to_post['signature'] = sign_data(stringify_for_signature(signed_fields)).decode('utf-8')
    return to_post


@sensitive_variables()
def process_cybersource_transmission(transmitted_data, fields):
    # Transmitted data must include signature, signed_field_names,
    # and all fields listed in signed_field_names
    try:
        signature = transmitted_data['signature']
        signed_field_names = transmitted_data['signed_field_names']
        signed_fields = OrderedDict()
        for field in signed_field_names.split(','):
            signed_fields[field] = transmitted_data[field]
    except KeyError as e:
        msg = 'Incomplete POST to CyberSource callback route: missing {}'.format(e)
        logger.warning(msg)
        raise InvalidTransmissionException(msg)

    # The signature must be valid
    if not is_valid_signature(signed_fields, signature):
        msg = 'Data with invalid signature POSTed to CyberSource callback route'
        logger.warning(msg)
        raise InvalidTransmissionException(msg)

    # Great! Return the subset of fields we want
    return retrieve_fields(transmitted_data, fields)


# Communicate with Perma

@sensitive_variables()
def prep_for_perma(dictionary):
    return encrypt_for_perma(stringify_data(dictionary))


@sensitive_variables()
def process_perma_transmission(transmitted_data, fields):
    # Transmitted data should contain a single field, 'encrypted_data', which
    # must be a JSON dict, encrypted by Perma and base64-encoded.
    encrypted_data = transmitted_data.get('encrypted_data', '')
    if not encrypted_data:
        raise InvalidTransmissionException('No encrypted_data in POST.')
    try:
        post_data = unstringify_data(decrypt_from_perma(encrypted_data))
    except Exception as e:
        logger.warning('Problem with transmitted data. {}'.format(format_exception(e)))
        raise InvalidTransmissionException(format_exception(e))

    # The encrypted data must include a valid timestamp.
    try:
        timestamp = post_data['timestamp']
    except KeyError:
        logger.warning('Missing timestamp in data.')
        raise InvalidTransmissionException('Missing timestamp in data.')
    if not is_valid_timestamp(timestamp, settings.PERMA_TIMESTAMP_MAX_AGE_SECONDS):
        logger.warning('Expired timestamp in data.')
        raise InvalidTransmissionException('Expired timestamp in data.')

    return retrieve_fields(post_data, fields)


# Helpers
def format_exception(e):
    return "{}: {}".format(type(e).__name__, e)


@sensitive_variables()
def retrieve_fields(transmitted_data, fields):
    try:
        data = {}
        for field in fields:
            data[field] = transmitted_data[field]
    except KeyError as e:
        msg = 'Incomplete data received: missing {}'.format(e)
        logger.warning(msg)
        raise InvalidTransmissionException(msg)
    return data


def is_valid_timestamp(stamp, max_age):
    return stamp <= (datetime.utcnow() + timedelta(seconds=max_age)).timestamp()


@sensitive_variables()
def stringify_data(data):
    """
    Takes any json-serializable data. Converts to a bytestring, suitable for passing to an encryption function.
    """
    return bytes(json.dumps(data, cls=DjangoJSONEncoder), 'utf-8')


@sensitive_variables()
def unstringify_data(data):
    """
    Reverses stringify_data. Takes a bytestring, returns deserialized json.
    """
    return json.loads(str(data, 'utf-8'))


@sensitive_variables()
def stringify_for_signature(data, sort=True):
    """
    Takes an ordered dict/mapping. Converts to a specially-formatted unicode string, suitable for
    generating a signature that Cybersource can verify.
    """
    if not sort and not isinstance(data, OrderedDict):
        # Otherwise, who knows what order we'll get!
        # (until python 3.6 brings sanity to the situation)
        raise TypeError('OrderedDict() required.')
    elif not isinstance(data, Mapping):
        raise TypeError
    return ','.join('{}={}'.format(key, data[key]) for key in (sorted(data) if sort else data))


@sensitive_variables()
def sign_data(data_string):
    """
    Sign with HMAC sha256 and base64 encode
    """
    message = bytes(data_string, 'utf-8')
    secret = bytes(settings.CS_SECRET_KEY, 'utf-8')
    hash = hmac.new(secret, message, hashlib.sha256)
    return base64.b64encode(hash.digest())


@sensitive_variables()
def safe_str_cmp(a: str, b: str) -> bool:
    """
    This function compares strings in somewhat constant time.  This
    requires that the length of at least one string is known in advance.
    Returns `True` if the two strings are equal, or `False` if they are not.
    Previously provided by werkzeug.
    """
    if isinstance(a, str):
        a = a.encode("utf-8")  # type: ignore

    if isinstance(b, str):
        b = b.encode("utf-8")  # type: ignore

    return hmac.compare_digest(a, b)


@sensitive_variables()
def is_valid_signature(data, signature):
    data_to_sign = stringify_for_signature(data, sort=False)
    return safe_str_cmp(signature, sign_data(data_to_sign))


@sensitive_variables()
def generate_public_private_keys():
    secret_a = PrivateKey.generate()
    public_a = secret_a.public_key
    secret_b = PrivateKey.generate()
    public_b = secret_b.public_key
    return {
        'a': {
            'secret': base64.b64encode(secret_a._private_key),
            'public': base64.b64encode(public_a._public_key),
        },
        'b': {
            'secret': base64.b64encode(secret_b._private_key),
            'public': base64.b64encode(public_b._public_key),
        }
    }


@sensitive_variables()
def encrypt_for_storage(message, encoder=encoding.Base64Encoder):
    """
    Public sealed box.
    http://pynacl.readthedocs.io/en/latest/public/#nacl-public-sealedbox
    """
    box = SealedBox(
        PublicKey(
            settings.STORAGE_ENCRYPTION_KEYS['vault_public_key'], encoder=encoder
        )
    )
    return box.encrypt(message)


@sensitive_variables()
def decrypt_from_storage(ciphertext, encoder=encoding.Base64Encoder):
    """
    Decrypt bytes encrypted via encrypt_for_storage

    To use in real life:
    -  get the vault secret key, and add to your local settings.py
    -  configure your local app to connect to your production database
    -  run python manage.py shell:
        >>> from perma_payments.models import *
        >>> from perma_payments.security import *
        >>> resp = SubscriptionRequestResponse.objects.get(pk=????????)
        >>> decrypt_from_storage(bytes(resp.full_response))
    """
    box = SealedBox(
        PrivateKey(
            settings.STORAGE_ENCRYPTION_KEYS['vault_secret_key'], encoder=encoder
        )
    )
    return box.decrypt(ciphertext)


@sensitive_variables()
def encrypt_for_perma(message, encoder=encoding.Base64Encoder):
    """
    Basic public key encryption ala pynacl.
    """
    box = Box(
        PrivateKey(
            settings.PERMA_ENCRYPTION_KEYS['perma_payments_secret_key'], encoder=encoder
        ),
        PublicKey(
            settings.PERMA_ENCRYPTION_KEYS['perma_public_key'], encoder=encoder
        )
    )
    return box.encrypt(message, encoder=encoder)


@sensitive_variables()
def decrypt_from_perma(ciphertext, encoder=encoding.Base64Encoder):
    """
    Decrypt bytes encrypted by perma.cc
    """
    box = Box(
        PrivateKey(
            settings.PERMA_ENCRYPTION_KEYS['perma_payments_secret_key'], encoder=encoder
        ),
        PublicKey(
            settings.PERMA_ENCRYPTION_KEYS['perma_public_key'], encoder=encoder
        )
    )
    return box.decrypt(ciphertext, encoder=encoder)
