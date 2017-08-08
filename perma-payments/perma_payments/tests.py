# from django.test import TestCase
from .security import *
from nacl.public import PrivateKey, PublicKey

def test_data_to_string_sorted():
    """
        Sorts keys alphabetically, joins in expected format.
    """
    data = {
        "foo": "baz",
        "bar": "bamph",
        "signed_field_names": "bar,foo,signed_field_names"
    }
    data_to_sign = data_to_string(data)
    assert data_to_sign == "bar=bamph,foo=baz,signed_field_names=bar,foo,signed_field_names"


def test_data_to_string_not_sorted():
    """
        Iterates in order, joins in expected format.
    """
    data = {
        "foo": "baz",
        "bar": "bamph",
        "signed_field_names": "foo,bar,signed_field_names"
    }
    data_to_sign = data_to_string(data, sort=False)
    assert data_to_sign == "foo=baz,bar=bamph,signed_field_names=foo,bar,signed_field_names"


def test_sign_data():
    """
        Checks using keys in settings_testing.py
    """
    data_string = "bar=bamph,foo=baz,signed_field_names=bar,foo,signed_field_names"
    assert sign_data(data_string) == b"wmEE0YLoDwXHf6kRe1e8AV9OcaFGNI+2qRQ8t9gS1Fk="


def test_generate_public_private_keys():
    keys = generate_public_private_keys()
    expected_keys = ['a', 'b']
    assert list(keys.keys()) == expected_keys
    for key in expected_keys:
        assert list(keys[key].keys()) == ['secret', 'public']
        assert keys[key]['secret'] != keys[key]['public']
        assert isinstance(PrivateKey(keys[key]['secret']), PrivateKey)
        assert isinstance(PublicKey(keys[key]['public']), PublicKey)


def test_storage_encrypt_and_decrypt():
    message = 'hi there'
    ci = encrypt_for_storage(bytes(message, 'utf-8'), (1).to_bytes(24, byteorder='big'))
    assert str(decrypt_from_storage(ci), 'utf-8') == message
