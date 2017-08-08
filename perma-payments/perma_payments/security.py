import hashlib
import hmac
import base64
from nacl.public import Box, PrivateKey, PublicKey

from django.conf import settings


def data_to_string(data, sort=True):
    return ','.join('{}={}'.format(key, data[key]) for key in (sorted(data) if sort else data))


def sign_data(data_string):
    """
    Sign with HMAC sha256 and base64 encode
    """
    message = bytes(data_string, 'utf-8')
    secret = bytes(settings.CS_SECRET_KEY, 'utf-8')
    hash = hmac.new(secret, message, hashlib.sha256)
    return base64.b64encode(hash.digest())


def generate_public_private_keys():
    secret_a = PrivateKey.generate()
    public_a = secret_a.public_key
    secret_b = PrivateKey.generate()
    public_b = secret_b.public_key
    return {
        'a': {
            'secret': secret_a._private_key,
            'public': public_a._public_key,
        },
        'b': {
            'secret': secret_b._private_key,
            'public': public_b._public_key,
        }
    }


def encrypt_for_storage(message, nonce):
    """
    Basic public key encryption ala pynacl.
    """
    box = Box(PrivateKey(settings.STORAGE_ENCRYPTION_KEYS['app_secret_key']), PublicKey(settings.STORAGE_ENCRYPTION_KEYS['vault_public_key']))
    return box.encrypt(message, nonce)


def decrypt_from_storage(ciphertext):
    """
    Decrypt bytes encrypted via encrypt_for_storage

    To use in real life: get the vault secret key, and add to settings.py:
    python manage.py shell
    >>> from perma_payments.models import *
    >>> from perma_payments.security import *
    >>> resp = SubscriptionRequestResponse.objects.get(pk=????????)
    >>> decrypt_full_response(bytes(resp.full_response))
    """
    box = Box(PrivateKey(settings.STORAGE_ENCRYPTION_KEYS['vault_secret_key']), PublicKey(settings.STORAGE_ENCRYPTION_KEYS['app_public_key']))
    return box.decrypt(ciphertext)
