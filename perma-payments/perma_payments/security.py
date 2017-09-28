import base64
from collections import OrderedDict, Mapping
from datetime import timedelta, datetime
import hashlib
import hmac
import json
from nacl import encoding
from nacl.public import Box, PrivateKey, PublicKey
from werkzeug.security import safe_str_cmp

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.debug import sensitive_variables

import logging
logger = logging.getLogger(__name__)

# for temporary implementation of SealedBox
from nacl import exceptions as exc
from nacl.encoding import Encodable, HexEncoder, RawEncoder
from nacl.hash import generichash
from nacl.utils import StringFixer

#
# Classes
#

class InvalidTransmissionException(Exception):
    pass


#
# Functions
#

# Communicate with CyberSource

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
    to_post['signature'] = sign_data(stringify_for_signature(signed_fields))
    return to_post


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

def prep_for_perma(dictionary):
    return encrypt_for_perma(stringify_data(dictionary))


def process_perma_transmission(transmitted_data, fields):
    # Transmitted data should contain a single field, 'encrypted_data', which
    # must be a JSON dict, encrypted by Perma and base64-encoded.
    encrypted_data = transmitted_data.get('encrypted_data','')
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


def stringify_data(data):
    """
    Takes any json-serializable data. Converts to a bytestring, suitable for passing to an encryption function.
    """
    return bytes(json.dumps(data, cls=DjangoJSONEncoder), 'utf-8')


def unstringify_data(data):
    """
    Reverses stringify_data. Takes a bytestring, returns deserialized json.
    """
    return json.loads(str(data, 'utf-8'))


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


def sign_data(data_string):
    """
    Sign with HMAC sha256 and base64 encode
    """
    message = bytes(data_string, 'utf-8')
    secret = bytes(settings.CS_SECRET_KEY, 'utf-8')
    hash = hmac.new(secret, message, hashlib.sha256)
    return base64.b64encode(hash.digest())


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
            'secret': secret_a._private_key,
            'public': public_a._public_key,
        },
        'b': {
            'secret': secret_b._private_key,
            'public': public_b._public_key,
        }
    }


def encrypt_for_storage(message):
    """
    Public sealed box.
    http://pynacl.readthedocs.io/en/latest/public/#nacl-public-sealedbox
    """
    box = SealedBox(PublicKey(settings.STORAGE_ENCRYPTION_KEYS['vault_public_key']))
    return box.encrypt(message)


@sensitive_variables()
def decrypt_from_storage(ciphertext):
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
    box = SealedBox(PrivateKey(settings.STORAGE_ENCRYPTION_KEYS['vault_secret_key']))
    return box.decrypt(ciphertext)


@sensitive_variables()
def encrypt_for_perma(message, encoder=encoding.Base64Encoder):
    """
    Basic public key encryption ala pynacl.
    """
    box = Box(PrivateKey(settings.PERMA_ENCRYPTION_KEYS['perma_payments_secret_key']), PublicKey(settings.PERMA_ENCRYPTION_KEYS['perma_public_key']))
    return box.encrypt(message, encoder=encoder)


@sensitive_variables()
def decrypt_from_perma(ciphertext, encoder=encoding.Base64Encoder):
    """
    Decrypt bytes encrypted by perma.cc
    """
    box = Box(PrivateKey(settings.PERMA_ENCRYPTION_KEYS['perma_payments_secret_key']), PublicKey(settings.PERMA_ENCRYPTION_KEYS['perma_public_key']))
    return box.decrypt(ciphertext, encoder=encoder)


#
# Temporary
#

# pure python version of SealedBox, until PyNacl 1.2.0 is released.
# from https://gist.github.com/lmctv/d76a2ebefd3227c461ff5450ea487a11
# when removing, remove imports from top of file

class SealedBox(Encodable, StringFixer, object):
    """
    A SealedBox implementation in terms of high-level
    :class:`~nacl.public.Box` APIs
    The SealedBox class boxes and unboxes messages between an ephemeral
    key-pair and a long-term one whose public key is known to the sender.
    The ciphertexts generated by this class include the public part
    of the ephemeral key before the :class:`~nacl.public.Box`
    ciphertext.
    :param public_key: :class:`~nacl.public.PublicKey` used to encrypt
            messages and derive nonces
    :param private_key: :class:`~nacl.public.PrivateKey` used to decrypt
            messages
    """

    def __init__(self, recipient_key):

        if isinstance(recipient_key, PublicKey):
            self.public_key = recipient_key
            self.private_key = None
        elif isinstance(recipient_key, PrivateKey):
            self.private_key = recipient_key
            self.public_key = recipient_key.public_key
        else:
            raise exc.TypeError("SealedBox must be created from "
                                "a PublicKey or a PrivateKey")

    def __bytes__(self):
        return self.public_key.encode(encoder=RawEncoder)

    def _get_nonce(self, pk1, pk2):
        nonce = generichash(bytes(pk1) + bytes(pk2),
                            digest_size=Box.NONCE_SIZE,
                            encoder=RawEncoder)
        return nonce

    def encrypt(self, plaintext, encoder=RawEncoder):
        """
        Encrypts the plaintext message using a random-generated ephemeral
        keypair and returns the ciphertext encoded with the encoder.
        :param plaintext: [:class:`bytes`] The plaintext message to encrypt
        :param encoder: The encoder to use to encode the ciphertext
        :rtype: [:class:`nacl.utils.EncryptedMessage`]
        """

        priv = PrivateKey.generate()
        nonce = self._get_nonce(priv.public_key, self.public_key)

        box = Box(priv, self.public_key)
        boxed = box.encrypt(plaintext, nonce=nonce, encoder=RawEncoder)

        encrypted = bytes(priv.public_key) + boxed.ciphertext

        encoded_ciphertext = encoder.encode(encrypted)

        return encoded_ciphertext

    def decrypt(self, ciphertext, encoder=RawEncoder):
        """
        Decrypts the ciphertext using the `nonce` (explicitly, when passed as a
        parameter or implicitly, when omitted, as part of the ciphertext) and
        returns the plaintext message.
        :param ciphertext: [:class:`bytes`] The encrypted message to decrypt
        :param nonce: [:class:`bytes`] The nonce used when encrypting the
            ciphertext
        :param encoder: The encoder used to decode the ciphertext.
        :rtype: [:class:`bytes`]
        """
        # Decode our ciphertext
        _ciphertext = encoder.decode(ciphertext)
        sender_pk = PublicKey(_ciphertext[:PublicKey.SIZE])
        ciphertext = _ciphertext[PublicKey.SIZE:]

        box = Box(self.private_key, sender_pk)

        nonce = self._get_nonce(sender_pk, self.public_key)

        plaintext = box.decrypt(ciphertext, nonce=nonce)

        return plaintext


if __name__ == '__main__':

    from binascii import hexlify, unhexlify

    # libsodium's test don't provide reference data for
    # the sealed box construction.
    # the following has been manually generated
    privalice = (b"77076d0a7318a57d3c16c17251b26645"
                 b"df4c2f87ebc0992ab177fba51db92c2a")
    pubalice = (b"8520f0098930a754748b7ddcb43ef75a"
                b"0dbf3a0d26381af4eba4a98eaa9b4e6a")
    plaintext = (b"be075fc53c81f2d5cf141316ebeb0c7b"
                 b"5228c52a4c62cbd44b66849b64244ffc"
                 b"e5ecbaaf33bd751a1ac728d45e6c6129"
                 b"6cdc3c01233561f41db66cce314adb31"
                 b"0e3be8250c46f06dceea3a7fa1348057"
                 b"e2f6556ad6b1318a024a838f21af1fde"
                 b"048977eb48f59ffd4924ca1c60902e52"
                 b"f0a089bc76897040e082f93776384864"
                 b"5e0705")
    encrypted = (b"199c808806a62c1be56951023ad3396b"
                 b"0ce0ef2c5b9ca688ac96d2d06ca43f65"
                 b"d314400cc9bbefb23dd26f824c9cb553"
                 b"f81e8c894ea9a553f4d777c77b66d5a6"
                 b"925da3f5961c5f7147172db5597ac142"
                 b"10066ee3ee13e6230a9a9610e9cddbf2"
                 b"4094f54fbbf6694c08a436cec39ff5a3"
                 b"73656d9584f4df9dd8c817e2e5975406"
                 b"28d0ee21a6524a3fcf3eabdc0968390b"
                 b"d260a47366ead7f71cc2e774d411d96f"
                 b"3497c7e10291937bc16dc46a111686b8"
                 b"5a8c86")

    # Create a SealedBox used to encrypt a message
    # which can be opened with a receiver's public key

    alice_pk = PublicKey(pubalice, encoder=HexEncoder)
    s_box = SealedBox(alice_pk)
    _encrypted = s_box.encrypt(unhexlify(plaintext))

    # sealed boxes encrypt using ephemeral keypairs;
    # since we expect they don't repeat:

    assert hexlify(_encrypted) != encrypted

    # Now, create a SealedBox used to decrypt messages
    # addressed to the receiver's keypair

    alice_sk = PrivateKey(privalice, encoder=HexEncoder)
    d_box = SealedBox(alice_sk)

    # Finally, check we can decrypt both the reference
    # cyphertext and the just generated one

    _m0 = d_box.decrypt(encrypted, encoder=HexEncoder)
    assert hexlify(_m0) == plaintext
    _m1 = d_box.decrypt(_encrypted)
    assert _m0 == _m1
