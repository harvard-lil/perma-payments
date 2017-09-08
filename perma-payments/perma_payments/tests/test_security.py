from datetime import datetime, timedelta
import decimal
from nacl.public import PrivateKey, PublicKey

from hypothesis import given
from hypothesis.strategies import text, integers, booleans, datetimes, dates, decimals, uuids, binary, lists, dictionaries
import pytest

from perma_payments.security import *

#
# UTILS
#
class SentinalException(Exception):
    pass


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


@pytest.fixture
def spoof_cybersource_post():
    data = {
        'signature': '',
        'signed_field_names': 'foo,bar',
        'foo': 'foo',
        'bar': 'bar',
        'desired_field': 'desired_field'
    }
    assert 'signature' in data
    assert 'signed_field_names' in data
    for field in data['signed_field_names'].split(','):
        assert field in data
    assert 'desired_field' in data
    return data


@pytest.fixture
def spoof_perma_post():
    # For convenience, spoofed data is not b64 encoded, encrypted or stringified
    data = {
        'encrypted_data': {"timestamp": 1504884268.560902, "desired_field": "desired_field"},
    }
    assert 'encrypted_data' in data
    assert 'timestamp' in data['encrypted_data']
    assert 'desired_field' in data['encrypted_data']
    return data


#
# TESTS
#

# Communicate with CyberSource

# def test_prep_for_cybersource_appropriate_fields_signed():
#     # blank signs {'unsigned_field_names': ''}
#     assert prep_for_cybersource({})['signature'] == b'6HuduuUJKfhKa8TR5qhELv+8uCdAPsJfkzIpNU88qEk='


# def test_prep_for_cybersource_unsigned_fields_are_not_signed():
#     pass


# def test_prep_for_cybersource_field_names_added_correctly():
#     assert prep_for_cybersource({})['signed_field_names'] == 'signed_field_names,unsigned_field_names'
#     assert prep_for_cybersource({})['unsigned_field_names'] is ''


# def test_prep_for_cybersource_unsigned_fields_optional():
#     assert prep_for_cybersource({})['unsigned_field_names'] is ''

# def prep_for_cybersource(signed_fields, unsigned_fields={}):
#     signed_fields['unsigned_field_names'] = ','.join(sorted(unsigned_fields))
#     signed_fields['signed_field_names'] = ''
#     signed_fields['signed_field_names'] = ','.join(sorted(signed_fields))
#     data_to_sign = stringify_for_signature(signed_fields)
#     to_post = {}
#     to_post.update(signed_fields)
#     to_post.update(unsigned_fields)
#     to_post['signature'] = sign_data(data_to_sign)
#     return to_post


def test_verify_cybersource_transmission_returns_desired_fields_when_all_is_well(spoof_cybersource_post, mocker):
    is_valid = mocker.patch('perma_payments.security.is_valid_signature', autospec=True, return_value=True)
    assert verify_cybersource_transmission(spoof_cybersource_post, ['desired_field']) == {'desired_field': 'desired_field'}
    is_valid.assert_called_once()


def test_verify_cybersource_transmission_missing_signature(spoof_cybersource_post):
    del spoof_cybersource_post['signature']
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_cybersource_transmission(spoof_cybersource_post, [])
    assert 'Incomplete POST' in str(excinfo)
    assert 'signature' in str(excinfo)


def test_verify_cybersource_transmission_missing_signed_field_names(spoof_cybersource_post):
    del spoof_cybersource_post['signed_field_names']
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_cybersource_transmission(spoof_cybersource_post, [])
    assert 'Incomplete POST' in str(excinfo)
    assert 'signed_field_names' in str(excinfo)


def test_verify_cybersource_transmission_missing_field_in_signed_field_names(spoof_cybersource_post):
    signed_field = spoof_cybersource_post['signed_field_names'].split(',').pop()
    del spoof_cybersource_post[signed_field]
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_cybersource_transmission(spoof_cybersource_post, [])
    assert 'Incomplete POST' in str(excinfo)


def test_verify_cybersource_transmission_invalid_signature(spoof_cybersource_post, mocker):
    is_valid = mocker.patch('perma_payments.security.is_valid_signature', autospec=True, return_value=False)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_cybersource_transmission(spoof_cybersource_post, [])
    is_valid.assert_called_once()
    assert 'Data with invalid signature' in str(excinfo)


def test_verify_cybersource_transmission_missing_arbitrary_field_we_require(spoof_cybersource_post, mocker):
    is_valid = mocker.patch('perma_payments.security.is_valid_signature', autospec=True, return_value=True)
    del spoof_cybersource_post['desired_field']
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_cybersource_transmission(spoof_cybersource_post, ['desired_field'])
    is_valid.assert_called_once()
    assert 'Incomplete data' in str(excinfo)
    assert 'desired_field' in str(excinfo)


# Communicate with Perma


def test_prep_for_perma():
    pass


# def prep_for_perma(dictionary):
#     return base64.b64encode(encrypt_for_perma(pack_data(dictionary)))


def test_verify_perma_transmission_encrypted_data_not_in_post():
    with pytest.raises(InvalidTransmissionException) as excinfo:
        assert verify_perma_transmission({}, [])
    assert 'No encrypted_data in POST.' in str(excinfo)


def test_verify_perma_transmission_encrypted_data_none():
    with pytest.raises(InvalidTransmissionException) as excinfo:
        assert verify_perma_transmission({'encrypted_data': None}, [])
    assert 'No encrypted_data in POST.' in str(excinfo)


def test_verify_perma_transmission_encrypted_data_empty():
    with pytest.raises(InvalidTransmissionException) as excinfo:
        assert verify_perma_transmission({'encrypted_data': ''}, [])
    assert 'No encrypted_data in POST.' in str(excinfo)


def test_verify_perma_transmission_not_b64encoded(spoof_perma_post, mocker):
    b64 = mocker.patch('perma_payments.security.base64.b64decode', autospec=True, side_effect=SentinalException)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_perma_transmission(spoof_perma_post, [])
    assert 'SentinalException' in str(excinfo)
    b64.assert_called_once()

def test_verify_perma_transmission_encryption_problem(spoof_perma_post, mocker):
    mocker.patch('perma_payments.security.base64.b64decode', autospec=True)
    decrypt = mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True, side_effect=SentinalException)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_perma_transmission(spoof_perma_post, [])
    assert 'SentinalException' in str(excinfo)
    decrypt.assert_called_once()

def test_verify_perma_transmission_not_valid_json(spoof_perma_post, mocker):
    mocker.patch('perma_payments.security.base64.b64decode', autospec=True)
    mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True)
    unstringify = mocker.patch('perma_payments.security.unstringify_data', autospec=True, side_effect=SentinalException)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_perma_transmission(spoof_perma_post, [])
    assert 'SentinalException' in str(excinfo)
    unstringify.assert_called_once()

def test_verify_perma_transmission_missing_timestamp(spoof_perma_post, mocker):
    mocker.patch('perma_payments.security.base64.b64decode', autospec=True)
    mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True)
    mocker.patch('perma_payments.security.unstringify_data', autospec=True, return_value=spoof_perma_post['encrypted_data'])
    del spoof_perma_post['encrypted_data']['timestamp']
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_perma_transmission(spoof_perma_post, [])
    assert 'Missing timestamp in data.' in str(excinfo)


def test_verify_perma_transmission_expired_timestamp(spoof_perma_post, mocker):
    mocker.patch('perma_payments.security.base64.b64decode', autospec=True)
    mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True)
    mocker.patch('perma_payments.security.unstringify_data', autospec=True, return_value=spoof_perma_post['encrypted_data'])
    mocker.patch('perma_payments.security.is_valid_timestamp', autospec=True, return_value=False)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        verify_perma_transmission(spoof_perma_post, [])
    assert 'Expired timestamp in data.' in str(excinfo)


def test_verify_perma_transmission_happy_path(spoof_perma_post, mocker):
    b64 = mocker.patch('perma_payments.security.base64.b64decode', autospec=True, return_value=mocker.sentinel.encrypted)
    decrypt = mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True, return_value=mocker.sentinel.decrypted)
    unstringify = mocker.patch('perma_payments.security.unstringify_data', autospec=True, return_value=spoof_perma_post['encrypted_data'])
    timestamp = mocker.patch('perma_payments.security.is_valid_timestamp', autospec=True, return_value=True)

    assert verify_perma_transmission(spoof_perma_post, ['desired_field']) == {'desired_field': 'desired_field'}
    b64.assert_called_once_with(spoof_perma_post['encrypted_data'])
    decrypt.assert_called_once_with(mocker.sentinel.encrypted)
    unstringify.assert_called_once_with(mocker.sentinel.decrypted)
    timestamp.assert_called_once_with(spoof_perma_post['encrypted_data']['timestamp'], settings.PERMA_TIMESTAMP_MAX_AGE_SECONDS)


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
