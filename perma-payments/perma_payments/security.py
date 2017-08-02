import hashlib
import hmac
import base64
import nacl.secret

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

def encrypt_for_storage(message, nonce):
    """
    Basic secret key encryption ala pynacl.
    """
    box = nacl.secret.SecretBox(settings.STORAGE_SECRET_KEY['key'])
    return box.encrypt(message, nonce)
