from datetime import datetime, timedelta
import decimal
from nacl.public import PrivateKey, PublicKey
from hypothesis import given
from hypothesis.strategies import text, integers, booleans, datetimes, dates, decimals, uuids, binary, lists, dictionaries

import pytest

from perma_payments.security import *

#
# FIXTURES
#

@pytest.fixture
def one_two_three_dict():
    data = {
        'one': 'one',
        'two': 'two',
        'three': 'three'
    }
    assert 'one' in data
    assert 'two' in data
    assert 'three' in data
    assert 'four' not in data
    return data


@pytest.fixture
def signed_field_names_sorted():
    data = {
        'foo': 'baz',
        'bar': 'bamph',
        'signed_field_names': 'bar,foo,signed_field_names'
    }
    fields_as_list = data['signed_field_names'].split(',')
    assert sorted(fields_as_list) == fields_as_list
    return data


@pytest.fixture
def signed_field_names_not_sorted():
    data = {
        'foo': 'baz',
        'bar': 'bamph',
        'signed_field_names': 'foo,bar,signed_field_names'
    }
    fields_as_list = data['signed_field_names'].split(',')
    assert sorted(fields_as_list) != fields_as_list
    return data


@pytest.fixture
def signed_data():
    """
        Uses keys in settings_testing.py
    """
    return {
        "data": {
            "bar": "bamph",
            "foo": "baz",
            "signed_field_names": "bar,foo,signed_field_names"
        },
        "string": "bar=bamph,foo=baz,signed_field_names=bar,foo,signed_field_names",
        "signature": b"wmEE0YLoDwXHf6kRe1e8AV9OcaFGNI+2qRQ8t9gS1Fk="
    }


# Helpers

def test_retrieve_fields_returns_only_specified_fields(one_two_three_dict):
    assert retrieve_fields(one_two_three_dict, ['one']) == {'one': 'one'}
    assert retrieve_fields(one_two_three_dict, ['two']) == {'two': 'two'}
    assert retrieve_fields(one_two_three_dict, ['one', 'three']) == {'one': 'one', 'three': 'three'}


def test_retrieve_fields_raises_if_field_absent(one_two_three_dict):
    with pytest.raises(InvalidTransmissionException):
        retrieve_fields(one_two_three_dict, ['four'])


def test_is_valid_timestamp():
    max_age = 60
    now = datetime.utcnow().timestamp()
    still_valid = (datetime.utcnow() + timedelta(seconds=max_age)).timestamp()
    invalid = (datetime.utcnow() + timedelta(seconds=max_age * 2)).timestamp()
    assert is_valid_timestamp(now, max_age)
    assert is_valid_timestamp(still_valid, max_age)
    assert not is_valid_timestamp(invalid, max_age)


preserved = text() | integers() | booleans()
@given(preserved | dictionaries(keys=text(), values=preserved))
def test_stringify_and_unstringify_data_types_preserved(data):
    assert unstringify_data(stringify_data(data)) == data


oneway = decimals(places=2, min_value=decimal.Decimal(0.00), allow_nan=False, allow_infinity=False) | datetimes() | dates() | uuids()
@given(oneway | dictionaries(keys=text(), values=oneway))
def test_stringify_types_lost(data):
    # Some types can be serialized, but not recovered from strings by json.loads.
    # Instead, you have to manually attempt to convert, by field, if you are expecting one of these types.
    #
    # If something can't be serialized, or unserialized,
    # this test will raise an Exception, rather than failing with an assertion error.
    unstringify_data(stringify_data(data))


@given(text() | integers() | booleans() | datetimes() | decimals() | binary() | lists(elements=text()))
def test_stringify_for_signature_fails_if_not_dict(x):
    with pytest.raises(TypeError):
        stringify_for_signature(x)


def test_stringify_for_signature_sorted(signed_field_names_sorted):
    """
        Sorts keys alphabetically, joins in expected format.
    """
    data_to_sign = stringify_for_signature(signed_field_names_sorted)
    assert data_to_sign == "bar=bamph,foo=baz,signed_field_names=bar,foo,signed_field_names"


def test_stringify_for_signature_not_sorted(signed_field_names_not_sorted):
    """
        Iterates in order, joins in expected format.
    """
    data_to_sign = stringify_for_signature(signed_field_names_not_sorted, sort=False)
    assert data_to_sign == "foo=baz,bar=bamph,signed_field_names=foo,bar,signed_field_names"


def test_sign_data(signed_data):
    assert sign_data(signed_data['string']) == signed_data['signature']


def test_is_valid_signature_valid(signed_data):
    assert is_valid_signature(signed_data['data'], signed_data['signature'])


def test_is_valid_signature_invalid(signed_data):
    assert not is_valid_signature(signed_data['data'], b"")


def test_generate_public_private_keys():
    keys = generate_public_private_keys()
    expected_keys = ['a', 'b']
    assert list(keys.keys()) == expected_keys
    for key in expected_keys:
        assert list(keys[key].keys()) == ['secret', 'public']
        assert keys[key]['secret'] != keys[key]['public']
        assert isinstance(PrivateKey(keys[key]['secret']), PrivateKey)
        assert isinstance(PublicKey(keys[key]['public']), PublicKey)


@given(binary())
def test_storage_encrypt_and_decrypt(b):
    ci = encrypt_for_storage(b, (1).to_bytes(24, byteorder='big'))
    assert decrypt_from_storage(ci) == b


@given(binary())
def test_perma_encrypt_and_decrypt(b):
    ci = encrypt_for_perma(b)
    assert decrypt_from_perma(ci) == b
