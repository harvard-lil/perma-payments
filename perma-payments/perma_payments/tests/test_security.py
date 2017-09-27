from collections import OrderedDict
from datetime import datetime, timedelta
import decimal
from django.http import QueryDict
from nacl.public import PrivateKey, PublicKey
from string import ascii_lowercase

from hypothesis import given
from hypothesis.strategies import characters, text, integers, booleans, datetimes, dates, decimals, uuids, binary, lists, dictionaries
import pytest

from perma_payments.security import *

from .utils import SentinelException

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
def reverse_ascii_ordered_dict():
    data = OrderedDict((c, c) for c in ascii_lowercase[::-1])
    assert list(data.keys()) != sorted(list(data.keys()))
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
    data = OrderedDict([
        ('foo', 'baz'),
        ('bar', 'bamph'),
        ('signed_field_names', 'foo,bar,signed_field_names')
    ])
    fields_as_list = data['signed_field_names'].split(',')
    assert sorted(fields_as_list) != fields_as_list
    return data


@pytest.fixture
def signed_data():
    """
        Uses keys in settings_testing.py
    """
    return {
        "data": OrderedDict([
            ("bar", "bamph"),
            ("foo", "baz"),
            ("signed_field_names", "bar,foo,signed_field_names")
        ]),
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


@pytest.fixture
def spoof_django_post_object():
    return QueryDict('a=1,b=2,c=3')


#
# TESTS
#

# Communicate with CyberSource

def test_prep_for_cybersource_unsigned_fields_optional():
    assert prep_for_cybersource({}) == prep_for_cybersource({}, {})


def test_prep_for_cybersource_signed_and_unsigned_field_names_added_and_listed_as_signed(one_two_three_dict, reverse_ascii_ordered_dict):
    assert prep_for_cybersource({})['signed_field_names'] == 'signed_field_names,unsigned_field_names'
    assert prep_for_cybersource({})['unsigned_field_names'] is ''


def test_prep_for_cybersource_signed_and_unsigned_fields_names_added(one_two_three_dict, reverse_ascii_ordered_dict):
    prepped = prep_for_cybersource(one_two_three_dict, reverse_ascii_ordered_dict)
    signed = prepped['signed_field_names'].split(',')
    unsigned = prepped['unsigned_field_names'].split(',')
    for key in one_two_three_dict:
        assert key in signed
        assert key not in unsigned
    for key in reverse_ascii_ordered_dict:
        assert key not in signed
        assert key in unsigned


def test_prep_for_cybersource_signed_and_unsigned_field_names_sorted(reverse_ascii_ordered_dict):
    prepped = prep_for_cybersource(reverse_ascii_ordered_dict, reverse_ascii_ordered_dict)
    signed = prepped['signed_field_names'].split(',')
    unsigned = prepped['unsigned_field_names'].split(',')
    assert signed == sorted(signed)
    assert unsigned == sorted(unsigned)


def test_prep_for_cybersource_all_input_fields_in_returned_data(one_two_three_dict, reverse_ascii_ordered_dict):
    prepped = prep_for_cybersource(one_two_three_dict, reverse_ascii_ordered_dict)
    for key, value in one_two_three_dict.items():
        assert prepped[key] == value
    for key, value in reverse_ascii_ordered_dict.items():
        assert prepped[key] == value


def test_prep_for_cybersource_signature(one_two_three_dict, reverse_ascii_ordered_dict, mocker):
    stringify = mocker.patch('perma_payments.security.stringify_for_signature', autospec=True, return_value=mocker.sentinel.stringified)
    sign = mocker.patch('perma_payments.security.sign_data', autospec=True, return_value=mocker.sentinel.signed)
    prepped = prep_for_cybersource(one_two_three_dict, reverse_ascii_ordered_dict)

    assert stringify.call_count == 1
    sign.assert_called_once_with(mocker.sentinel.stringified)
    assert 'signature' in prepped
    assert prepped['signature'] == mocker.sentinel.signed


def test_process_cybersource_transmission_returns_desired_fields_when_all_is_well(spoof_cybersource_post, mocker):
    is_valid = mocker.patch('perma_payments.security.is_valid_signature', autospec=True, return_value=True)
    assert process_cybersource_transmission(spoof_cybersource_post, ['desired_field']) == {'desired_field': 'desired_field'}
    assert is_valid.call_count == 1


def test_process_cybersource_transmission_missing_signature(spoof_cybersource_post):
    del spoof_cybersource_post['signature']
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_cybersource_transmission(spoof_cybersource_post, [])
    assert 'Incomplete POST' in str(excinfo)
    assert 'signature' in str(excinfo)


def test_process_cybersource_transmission_missing_signed_field_names(spoof_cybersource_post):
    del spoof_cybersource_post['signed_field_names']
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_cybersource_transmission(spoof_cybersource_post, [])
    assert 'Incomplete POST' in str(excinfo)
    assert 'signed_field_names' in str(excinfo)


def test_process_cybersource_transmission_missing_field_in_signed_field_names(spoof_cybersource_post):
    signed_field = spoof_cybersource_post['signed_field_names'].split(',').pop()
    del spoof_cybersource_post[signed_field]
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_cybersource_transmission(spoof_cybersource_post, [])
    assert 'Incomplete POST' in str(excinfo)


def test_process_cybersource_transmission_invalid_signature(spoof_cybersource_post, mocker):
    is_valid = mocker.patch('perma_payments.security.is_valid_signature', autospec=True, return_value=False)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_cybersource_transmission(spoof_cybersource_post, [])
    assert is_valid.call_count == 1
    assert 'Data with invalid signature' in str(excinfo)


def test_process_cybersource_transmission_missing_arbitrary_field_we_require(spoof_cybersource_post, mocker):
    is_valid = mocker.patch('perma_payments.security.is_valid_signature', autospec=True, return_value=True)
    del spoof_cybersource_post['desired_field']
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_cybersource_transmission(spoof_cybersource_post, ['desired_field'])
    assert is_valid.call_count == 1
    assert 'Incomplete data' in str(excinfo)
    assert 'desired_field' in str(excinfo)


# Communicate with Perma


def test_prep_for_perma(mocker):
    stringify = mocker.patch('perma_payments.security.stringify_data', autospec=True, return_value=mocker.sentinel.stringified)
    encrypt = mocker.patch('perma_payments.security.encrypt_for_perma', autospec=True, return_value=mocker.sentinel.encrypted)

    assert prep_for_perma({}) == mocker.sentinel.encrypted
    stringify.assert_called_once_with({})
    encrypt.assert_called_once_with(mocker.sentinel.stringified)


def test_process_perma_transmission_encrypted_data_not_in_post():
    with pytest.raises(InvalidTransmissionException) as excinfo:
        assert process_perma_transmission({}, [])
    assert 'No encrypted_data in POST.' in str(excinfo)


def test_process_perma_transmission_encrypted_data_none():
    with pytest.raises(InvalidTransmissionException) as excinfo:
        assert process_perma_transmission({'encrypted_data': None}, [])
    assert 'No encrypted_data in POST.' in str(excinfo)


def test_process_perma_transmission_encrypted_data_empty():
    with pytest.raises(InvalidTransmissionException) as excinfo:
        assert process_perma_transmission({'encrypted_data': ''}, [])
    assert 'No encrypted_data in POST.' in str(excinfo)


def test_process_perma_transmission_encryption_problem(spoof_perma_post, mocker):
    decrypt = mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True, side_effect=SentinelException)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_perma_transmission(spoof_perma_post, [])
    assert 'SentinelException' in str(excinfo)
    assert decrypt.call_count == 1


def test_process_perma_transmission_not_valid_json(spoof_perma_post, mocker):
    mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True)
    unstringify = mocker.patch('perma_payments.security.unstringify_data', autospec=True, side_effect=SentinelException)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_perma_transmission(spoof_perma_post, [])
    assert 'SentinelException' in str(excinfo)
    assert unstringify.call_count == 1


def test_process_perma_transmission_missing_timestamp(spoof_perma_post, mocker):
    mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True)
    mocker.patch('perma_payments.security.unstringify_data', autospec=True, return_value=spoof_perma_post['encrypted_data'])
    del spoof_perma_post['encrypted_data']['timestamp']
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_perma_transmission(spoof_perma_post, [])
    assert 'Missing timestamp in data.' in str(excinfo)


def test_process_perma_transmission_expired_timestamp(spoof_perma_post, mocker):
    mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True)
    mocker.patch('perma_payments.security.unstringify_data', autospec=True, return_value=spoof_perma_post['encrypted_data'])
    mocker.patch('perma_payments.security.is_valid_timestamp', autospec=True, return_value=False)
    with pytest.raises(InvalidTransmissionException) as excinfo:
        process_perma_transmission(spoof_perma_post, [])
    assert 'Expired timestamp in data.' in str(excinfo)


def test_process_perma_transmission_happy_path(spoof_perma_post, mocker):
    decrypt = mocker.patch('perma_payments.security.decrypt_from_perma', autospec=True, return_value=mocker.sentinel.decrypted)
    unstringify = mocker.patch('perma_payments.security.unstringify_data', autospec=True, return_value=spoof_perma_post['encrypted_data'])
    timestamp = mocker.patch('perma_payments.security.is_valid_timestamp', autospec=True, return_value=True)

    assert process_perma_transmission(spoof_perma_post, ['desired_field']) == {'desired_field': 'desired_field'}

    decrypt.assert_called_once_with(spoof_perma_post['encrypted_data'])
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


preserved = text(alphabet=characters(min_codepoint=1, blacklist_categories=('Cc', 'Cs'))) | integers() | booleans()
@given(preserved | dictionaries(keys=text(alphabet=characters(min_codepoint=1, blacklist_categories=('Cc', 'Cs'))), values=preserved))
def test_stringify_and_unstringify_data_types_preserved(data):
    assert unstringify_data(stringify_data(data)) == data


oneway = decimals(places=2, min_value=decimal.Decimal(0.00), allow_nan=False, allow_infinity=False) | datetimes() | dates() | uuids()
@given(oneway | dictionaries(keys=text(alphabet=characters(min_codepoint=1, blacklist_categories=('Cc', 'Cs'))), values=oneway))
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


def test_stringify_for_signature_not_sorted_type_error(signed_field_names_sorted):
    with pytest.raises(TypeError):
        stringify_for_signature(signed_field_names_not_sorted, sort=False)


def test_sign_data(signed_data):
    assert sign_data(signed_data['string']) == signed_data['signature']


def test_is_valid_signature_valid(signed_data):
    assert is_valid_signature(signed_data['data'], signed_data['signature'])


def test_is_valid_signature_invalid(signed_data):
    assert not is_valid_signature(signed_data['data'], b"")


def test_generate_public_private_keys():
    keys = generate_public_private_keys()
    expected_keys = ['a', 'b']
    assert sorted(list(keys.keys())) == sorted(expected_keys)
    for key in expected_keys:
        assert sorted(list(keys[key].keys())) == sorted(['secret', 'public'])
        assert keys[key]['secret'] != keys[key]['public']
        assert isinstance(PrivateKey(keys[key]['secret']), PrivateKey)
        assert isinstance(PublicKey(keys[key]['public']), PublicKey)


@given(binary())
def test_storage_encrypt_and_decrypt(b):
    ci = encrypt_for_storage(b)
    assert decrypt_from_storage(ci) == b


@given(binary())
def test_perma_encrypt_and_decrypt(b):
    ci = encrypt_for_perma(b)
    assert decrypt_from_perma(ci) == b
