import io

import pytest

from perma_payments.views import SENSITIVE_POST_PARAMETERS, redact, skip_lines


#
# FIXTURES
#

@pytest.fixture()
def senstive_dict():
    data = {
        'payment_token': 'payment_token',
        'req_access_key': 'req_access_key',
        'req_bill_to_address_city': 'req_bill_to_address_city',
        'req_bill_to_address_country': 'req_bill_to_address_country',
        'req_bill_to_address_line1': 'req_bill_to_address_line1',
        'req_bill_to_address_postal_code': 'req_bill_to_address_postal_code',
        'req_bill_to_address_state': 'req_bill_to_address_state',
        'req_bill_to_email': 'req_bill_to_email',
        'req_bill_to_forename': 'req_bill_to_forename',
        'req_bill_to_surname': 'req_bill_to_surname',
        'req_card_expiry_date': 'req_card_expiry_date',
        'req_card_number': 'req_card_number',
        'req_payment_token': 'req_payment_token',
        'req_profile_id': 'req_profile_id',
        'signature': 'signature',
        'NOTSECRET1': 'NOTSECRET1',
        'NOTSECRET2': 'NOTSECRET2'
    }
    for field in SENSITIVE_POST_PARAMETERS:
        assert field in data
    for field in ['NOTSECRET1', 'NOTSECRET2']:
        assert field in data
    return data


@pytest.fixture()
def five_line_file():
    file = io.StringIO("line1\nline2\nline3\nline4\nline5\n")
    assert 5 == sum(1 for line in file)
    file.seek(0)
    return file


#
# TESTS
#

def test_skip_lines(five_line_file):
    skip_lines(five_line_file, 4)
    assert five_line_file.readline() == 'line5\n'


def test_redact(senstive_dict):
    redacted = redact(senstive_dict)
    for field in SENSITIVE_POST_PARAMETERS:
        assert field not in redacted
    for field in ['NOTSECRET1', 'NOTSECRET2']:
        assert field in redacted
