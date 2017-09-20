from datetime import datetime, timezone
import decimal
import random
import io
import urllib

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict

# from hypothesis import given
from hypothesis.strategies import decimals
import pytest

from perma_payments.models import STANDING_STATUSES, SubscriptionAgreement, SubscriptionRequest
from perma_payments.security import InvalidTransmissionException
from perma_payments.views import *

#
# Here, we are testing urls.py, views.py, and template rendering
# all in one spot, for simplicity.
#

#
# UTILS
#
genesis = datetime.fromtimestamp(0).replace(tzinfo=timezone.utc)
registrar_id = random.randint(1, 1000)
# reason_code = random.randint(1, 1000)
recurring_frequency = random.choice([status[0] for status in SubscriptionRequest._meta.get_field('recurring_frequency').choices])
amount = decimals(places=2, min_value=decimal.Decimal(0.00), allow_nan=False, allow_infinity=False).example()
recurring_amount = decimals(places=2, min_value=decimal.Decimal(0.00), allow_nan=False, allow_infinity=False).example()
# message = text(alphabet=characters(min_codepoint=1, blacklist_categories=('Cc', 'Cs'))).example()
# payment_token = text(alphabet="0123456789", min_size=26, max_size=26).example()
# post = QueryDict('a=1,b=2,c=3')

sentinel_bytes = b'sentinel_bytes'

def expected_template_used(response, expected):
    template_list = [template.name for template in response.templates]
    assert expected in template_list


def get_not_allowed(client, route):
    response = client.get(route)
    assert response.status_code == 405


def post_not_allowed(client, route):
    response = client.post(route)
    assert response.status_code == 405


def put_patch_delete_not_allowed(client, route):
    response = client.patch(route)
    assert response.status_code == 405
    response = client.put(route)
    assert response.status_code == 405
    response = client.delete(route)
    assert response.status_code == 405


def dict_to_querydict(d):
    return QueryDict(urllib.parse.urlencode(d))


#
# FIXTURES
#

@pytest.fixture
def index():
    return {
        'route': '/',
        'template': 'generic.html'
    }


@pytest.fixture
def subscribe():
    data = {
        'route': '/subscribe/',
        'template': 'redirect.html',
        'valid_data': {
            'registrar': registrar_id,
            'amount': amount,
            'recurring_amount': recurring_amount,
            'recurring_frequency': recurring_frequency,
            'recurring_start_date': genesis
        }
    }
    for field in FIELDS_REQUIRED_FROM_PERMA['subscribe']:
        assert field in data['valid_data']
    return data


@pytest.fixture
def subscribe_redirect_fields():
    return {field: field for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['subscribe']}


@pytest.fixture
def update():
    data = {
        'route': '/update/',
        'template': 'redirect.html',
        'valid_data': {
            'registrar': registrar_id
        }
    }
    for field in FIELDS_REQUIRED_FROM_PERMA['update']:
        assert field in data['valid_data']
    return data


@pytest.fixture
def update_redirect_fields():
    return {field: field for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['update']}


@pytest.fixture
def cybersource_callback():
    return {
        'route': '/cybersource-callback/',
        'template': 'redirect.html',
        'valid_data': {
            'req_transaction_uuid': 'sentinel string',
            'decision': 'sentinel string',
            'reason_code': 'sentinel string',
            'message': 'sentinel string',
            'payment_token': 'sentinel string'
        },
        'invalid_payment_token': {
            'req_transaction_uuid': 'sentinel string',
            'decision': 'sentinel string',
            'reason_code': 'sentinel string',
            'message': 'sentinel string',
            'payment_token': '1234567890123456'
        }
    }


@pytest.fixture
def subscription():
    return {
        'route': '/subscription/',
        'valid_data': {
            'registrar': registrar_id
        }
    }


@pytest.fixture
def cancel_request():
    return {
        'route': '/cancel-request/',
        'valid_data': {
            'registrar': registrar_id
        }
    }


@pytest.fixture
def update_statuses(status_csv):
    return {
        'route': '/update-statuses/',
        'valid_data': {
            'csv_file': status_csv
        }
    }


@pytest.fixture
def status_csv():
    output = io.StringIO()
    fieldnames = ['Merchant Reference Code', 'Status']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow({'Merchant Reference Code': 'ref1', 'Status': 'Updated'})
    writer.writerow({'Merchant Reference Code': 'ref2', 'Status': 'Updated'})
    return SimpleUploadedFile("csv.csv", bytes(output.getvalue(), 'utf-8'), content_type="text/csv")


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def complete_standing_sa(request):
    sa = SubscriptionAgreement(
        registrar=registrar_id,
        status=request.param
    )
    sa.save()
    sr = SubscriptionRequest(
        subscription_agreement=sa,
        amount=amount,
        recurring_amount=recurring_amount,
        recurring_start_date=genesis,
        recurring_frequency=recurring_frequency
    )
    sr.save()
    assert not sa.cancellation_requested
    assert sa.can_be_altered
    assert sa.status != 'Updated'
    return sa


@pytest.fixture()
@pytest.mark.django_db
def non_admin():
    return User.objects.create_user('joe')


@pytest.fixture()
def five_line_file():
    file = io.StringIO("line1\nline2\nline3\nline4\nline5\n")
    assert 5 == sum(1 for line in file)
    file.seek(0)
    return file


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
        'FINE1': 'FINE1',
        'FINE2': 'FINE2'
    }
    for field in SENSITIVE_POST_PARAMETERS:
        assert field in data
    for field in ['FINE1', 'FINE2']:
        assert field in data
    return data


#
# TESTS
#


# utils

def test_skip_lines(five_line_file):
    skip_lines(five_line_file, 4)
    assert five_line_file.readline() == 'line5\n'


def test_redact(senstive_dict):
    redacted = redact(senstive_dict)
    for field in SENSITIVE_POST_PARAMETERS:
        assert field not in redacted
    for field in ['FINE1', 'FINE2']:
        assert field in redacted


#
# OMG these are ALL RIDICULOUS.
# Maybe I should break these views out into smaller functions.......
#

# index

def test_index_get(client, index):
    response = client.get(index['route'])
    assert response.status_code == 200
    expected_template_used(response, index['template'])


def test_index_other_methods(client, index):
    post_not_allowed(client, index['route'])
    put_patch_delete_not_allowed(client, index['route'])


# subscribe

def test_subscribe_post_invalid_perma_transmission(client, subscribe, mocker):
    # mocks
    process = mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, side_effect=InvalidTransmissionException)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value

    # request
    response = client.post(subscribe['route'], subscribe['valid_data'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    process.assert_called_once_with(dict_to_querydict(subscribe['valid_data']), FIELDS_REQUIRED_FROM_PERMA['subscribe'])
    assert not sa_instance.save.called
    assert not sr_instance.save.called


def test_subscribe_post_already_standing_subscription(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa.registrar_standing_subscription.return_value=sa_instance
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value

    # request
    response = client.post(subscribe['route'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b'already have a subscription' in response.content
    sa.registrar_standing_subscription.assert_called_once_with(subscribe['valid_data']['registrar'])
    assert not sa_instance.save.called
    assert not sr_instance.save.called


def test_subscribe_post_sa_validation_fails(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.registrar_standing_subscription.return_value = None
    sa_instance = sa.return_value
    sa_instance.full_clean.side_effect=ValidationError('oh no!')
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value
    log = mocker.patch('perma_payments.views.logger.warning', autospec=True)

    # request
    response = client.post(subscribe['route'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    sa_instance.full_clean.assert_called_once()
    assert not sa_instance.save.called
    assert not sr_instance.save.called
    log.assert_called_once()


def test_subscribe_post_sr_validation_fails(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.registrar_standing_subscription.return_value = None
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value
    sr_instance.full_clean.side_effect=ValidationError('oh no!')
    log = mocker.patch('perma_payments.views.logger.warning', autospec=True)

    # request
    response = client.post(subscribe['route'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    sr_instance.full_clean.assert_called_once()
    assert not sr_instance.save.called
    log.assert_called_once()


def test_subscribe_post_sa_and_sr_validated_and_saved_correctly(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.registrar_standing_subscription.return_value = None
    sa_instance = sa.return_value
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value

    # request
    response = client.post(subscribe['route'])

    # assertions
    assert response.status_code == 200
    sa.assert_called_once_with(
        registrar=subscribe['valid_data']['registrar'],
        status='Pending'
    )
    sa_instance.full_clean.assert_called_once()
    sa_instance.save.assert_called_once()
    sr.assert_called_once_with(
        subscription_agreement=sa_instance,
        amount=subscribe['valid_data']['amount'],
        recurring_amount=subscribe['valid_data']['recurring_amount'],
        recurring_frequency=subscribe['valid_data']['recurring_frequency'],
        recurring_start_date=subscribe['valid_data']['recurring_start_date']
    )
    sr_instance.full_clean.assert_called_once()
    sr_instance.save.assert_called_once()


def test_subscribe_post_data_prepped_correctly(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.registrar_standing_subscription.return_value = None
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value
    prepped = mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True)

    # request
    response = client.post(subscribe['route'])

    # assertions
    assert response.status_code == 200
    fields_to_prep = {
        'access_key': settings.CS_ACCESS_KEY,
        'amount': sr_instance.amount,
        'currency': sr_instance.currency,
        'locale': sr_instance.locale,
        'payment_method': sr_instance.payment_method,
        'profile_id': settings.CS_PROFILE_ID,
        'recurring_amount': sr_instance.recurring_amount,
        'recurring_frequency': sr_instance.recurring_frequency,
        'recurring_start_date': sr_instance.get_formatted_start_date(),
        'reference_number': sr_instance.reference_number,
        'signed_date_time': sr_instance.get_formatted_datetime(),
        'transaction_type': sr_instance.transaction_type,
        'transaction_uuid': sr_instance.transaction_uuid,
    }
    prepped.assert_called_once_with(fields_to_prep)
    for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['subscribe']:
        assert field in fields_to_prep


def test_subscribe_post_redirect_form_populated_correctly(client, subscribe, subscribe_redirect_fields, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.registrar_standing_subscription.return_value = None
    mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True, return_value=subscribe_redirect_fields)

    # request
    response = client.post(subscribe['route'])

    # assertions
    assert response.status_code == 200
    assert response.context['fields_to_post'] == subscribe_redirect_fields
    context = list(response.context.keys())
    for field in ['fields_to_post', 'post_to_url']:
        assert field in context
    expected_template_used(response, 'redirect.html')
    for field in subscribe_redirect_fields:
        assert bytes('<input type="hidden" name="{0}" value="{0}">'.format(field), 'utf-8') in response.content


def test_subscribe_other_methods(client, subscribe):
    get_not_allowed(client, subscribe['route'])
    put_patch_delete_not_allowed(client, subscribe['route'])


# update

def test_update_post_invalid_perma_transmission(client, update, mocker):
    # mocks
    process = mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, side_effect=InvalidTransmissionException)
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value

    # request
    response = client.post(update['route'], update['valid_data'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    process.assert_called_once_with(dict_to_querydict(update['valid_data']), FIELDS_REQUIRED_FROM_PERMA['update'])
    assert not ur_instance.save.called


def test_update_post_no_standing_subscription(client, update, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.registrar_standing_subscription.return_value = None
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value

    # request
    response = client.post(update['route'], update['valid_data'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"can't find any active subscriptions" in response.content
    sa.registrar_standing_subscription.assert_called_once_with(update['valid_data']['registrar'])
    assert not ur_instance.save.called


def test_update_post_subscription_unalterable(client, update, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa_instance.can_be_altered.return_value = False
    sa.registrar_standing_subscription.return_value = sa_instance
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value

    # request
    response = client.post(update['route'], update['valid_data'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"can't find any active subscriptions" in response.content
    sa_instance.can_be_altered.assert_called_once()
    assert not ur_instance.save.called


def test_update_post_ur_validation_fails(client, update, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa_instance.can_be_altered.return_value = True
    sa.registrar_standing_subscription.return_value = sa_instance
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value
    ur_instance.full_clean.side_effect=ValidationError('oh no!')
    log = mocker.patch('perma_payments.views.logger.warning', autospec=True)

    # request
    response = client.post(update['route'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    ur_instance.full_clean.assert_called_once()
    assert not ur_instance.save.called
    log.assert_called_once()


def test_update_post_ur_validated_and_saved_correctly(client, update, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa.registrar_standing_subscription.return_value = sa_instance
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value

    # request
    response = client.post(update['route'])

    # assertions
    assert response.status_code == 200
    ur.assert_called_once_with(
        subscription_agreement=sa_instance
    )
    ur_instance.full_clean.assert_called_once()
    ur_instance.save.assert_called_once()


def test_update_post_data_prepped_correctly(client, update, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa.registrar_standing_subscription.return_value = sa_instance
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value
    srr = mocker.patch('perma_payments.views.SubscriptionRequestResponse', autospec=True)
    srr_instance = srr.return_value
    sa_instance.subscription_request = sr_instance
    sr_instance.subscription_request_response = srr_instance
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value
    prepped = mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True)

    # request
    response = client.post(update['route'])

    # assertions
    assert response.status_code == 200
    fields_to_prep = {
        'access_key': settings.CS_ACCESS_KEY,
        'allow_payment_token_update': 'true',
        'locale': sr_instance.locale,
        'payment_method': sr_instance.payment_method,
        'payment_token': srr_instance.payment_token,
        'profile_id': settings.CS_PROFILE_ID,
        'reference_number': sr_instance.reference_number,
        'signed_date_time': ur_instance.get_formatted_datetime(),
        'transaction_type': ur_instance.transaction_type,
        'transaction_uuid': ur_instance.transaction_uuid,
    }
    prepped.assert_called_once_with(fields_to_prep)
    for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['update']:
        assert field in fields_to_prep


def test_update_post_redirect_form_populated_correctly(client, update, update_redirect_fields, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa.registrar_standing_subscription.return_value = sa_instance
    mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    mocker.patch('perma_payments.views.SubscriptionRequestResponse', autospec=True)
    mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True, return_value=update_redirect_fields)


    # request
    response = client.post(update['route'])

    # assertions
    assert response.status_code == 200
    assert response.context['fields_to_post'] == update_redirect_fields
    context = list(response.context.keys())
    for field in ['fields_to_post', 'post_to_url']:
        assert field in context
    expected_template_used(response, 'redirect.html')
    for field in update_redirect_fields:
        assert bytes('<input type="hidden" name="{0}" value="{0}">'.format(field), 'utf-8') in response.content


def test_update_other_methods(client, update):
    get_not_allowed(client, update['route'])
    put_patch_delete_not_allowed(client, update['route'])


# cybersource_callback

def test_cybersource_callback_post(client, cybersource_callback, mocker):
    pass


def test_cybersource_callback_post_invalid_transmission(client, cybersource_callback, mocker):
    process = mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, side_effect=InvalidTransmissionException)

    # request
    response = client.post(cybersource_callback['route'], cybersource_callback['valid_data'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    process.assert_called_once_with(dict_to_querydict(cybersource_callback['valid_data']), FIELDS_REQUIRED_FROM_CYBERSOURCE['cybersource_callback'])


@pytest.mark.django_db
def test_cybersource_callback_post_update_request(client, cybersource_callback, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    mocked_related_request = sa_instance.update_request
    ot = mocker.patch('perma_payments.views.OutgoingTransaction', autospec=True)
    ot.objects.get.return_value = mocked_related_request
    check_type = mocker.patch('perma_payments.views.isinstance', return_value=True)
    r = mocker.patch('perma_payments.views.Response', autospec=True)

    # request
    response = client.post(cybersource_callback['route'], cybersource_callback['valid_data'])

    # assertions
    ot.objects.get.assert_called_once_with(transaction_uuid=cybersource_callback['valid_data']['req_transaction_uuid'])
    check_type.assert_called_once()
    r.save_new_w_encryped_full_response.assert_called_once_with(
        UpdateRequestResponse,
        dict_to_querydict(cybersource_callback['valid_data']),
        {
            'related_request': mocked_related_request,
            'decision': cybersource_callback['valid_data']['decision'],
            'reason_code': cybersource_callback['valid_data']['reason_code'],
            'message': cybersource_callback['valid_data']['message']
        }
    )
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b'OK' in response.content


@pytest.mark.django_db
def test_cybersource_callback_post_subscription_request(client, cybersource_callback, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    mocked_related_request = sa_instance.subscription_request
    ot = mocker.patch('perma_payments.views.OutgoingTransaction', autospec=True)
    ot.objects.get.return_value = mocked_related_request
    check_type = mocker.patch('perma_payments.views.isinstance', side_effect=[False, True])
    r = mocker.patch('perma_payments.views.Response', autospec=True)

    # request
    response = client.post(cybersource_callback['route'], cybersource_callback['valid_data'])

    # assertions
    ot.objects.get.assert_called_once_with(transaction_uuid=cybersource_callback['valid_data']['req_transaction_uuid'])
    assert check_type.call_count == 2
    r.save_new_w_encryped_full_response.assert_called_once_with(
        SubscriptionRequestResponse,
        dict_to_querydict(cybersource_callback['valid_data']),
        {
            'related_request': mocked_related_request,
            'decision': cybersource_callback['valid_data']['decision'],
            'reason_code': cybersource_callback['valid_data']['reason_code'],
            'message': cybersource_callback['valid_data']['message'],
            'payment_token': cybersource_callback['valid_data']['payment_token']
        }
    )
    mocked_related_request.subscription_agreement.update_status_after_cs_decision.assert_called_once_with(
        cybersource_callback['valid_data']['decision'],
        redact(cybersource_callback['valid_data'])
    )
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b'OK' in response.content


@pytest.mark.django_db
def test_cybersource_callback_payment_token_invalid(client, cybersource_callback, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['invalid_payment_token'])
    mocker.patch('perma_payments.views.OutgoingTransaction', autospec=True)
    mocker.patch('perma_payments.views.isinstance', side_effect=[False, True])
    mocker.patch('perma_payments.views.Response', autospec=True)
    log = mocker.patch('perma_payments.views.logger.error', autospec=True)

    client.post(cybersource_callback['route'], cybersource_callback['invalid_payment_token'])

    log.assert_called_once()


@pytest.mark.django_db
def test_cybersource_callback_post_type_not_handled(client, cybersource_callback, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['valid_data'])
    mocker.patch('perma_payments.views.OutgoingTransaction', autospec=True)
    mocker.patch('perma_payments.views.isinstance', return_value=False)
    with pytest.raises(NotImplementedError):
        client.post(cybersource_callback['route'])


def test_cybersource_callback_other_methods(client, cybersource_callback):
    get_not_allowed(client, cybersource_callback['route'])
    put_patch_delete_not_allowed(client, cybersource_callback['route'])


# subscription

def test_subscription_post_invalid_transmission(client, subscription, mocker):
    process = mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, side_effect=InvalidTransmissionException)

    # request
    response = client.post(subscription['route'], subscription['valid_data'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    process.assert_called_once_with(dict_to_querydict(subscription['valid_data']), FIELDS_REQUIRED_FROM_PERMA['subscription'])


def test_subscription_post_no_standing_subscription(client, subscription, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.registrar_standing_subscription.return_value = None
    d = mocker.patch('perma_payments.views.datetime', autospec=True)
    d.utcnow.return_value.timestamp.return_value = mocker.sentinel.timestamp
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=sentinel_bytes)

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    d.utcnow.return_value.timestamp.assert_called_once()
    sa.registrar_standing_subscription.assert_called_once_with(subscription['valid_data']['registrar'])
    prepped.assert_called_once_with({
        'registrar': subscription['valid_data']['registrar'],
        'subscription': None,
        'timestamp': mocker.sentinel.timestamp
    })
    r = response.json()
    assert r and list(r.keys()) == ['encrypted_data']
    assert r['encrypted_data'] == sentinel_bytes.decode('utf-8')


def test_subscription_post_standing_subscription(client, subscription, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa_instance.cancellation_requested = False
    sa.registrar_standing_subscription.return_value = sa_instance
    d = mocker.patch('perma_payments.views.datetime', autospec=True)
    d.utcnow.return_value.timestamp.return_value = mocker.sentinel.timestamp
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=sentinel_bytes)

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    sa.registrar_standing_subscription.assert_called_once_with(subscription['valid_data']['registrar'])
    prepped.assert_called_once_with({
        'registrar': subscription['valid_data']['registrar'],
        'subscription': {
            'rate': sa_instance.subscription_request.recurring_amount,
            'frequency': sa_instance.subscription_request.recurring_frequency,
            'status': sa_instance.status
        },
        'timestamp': mocker.sentinel.timestamp
    })
    r = response.json()
    assert r and list(r.keys()) == ['encrypted_data']
    assert r['encrypted_data'] == sentinel_bytes.decode('utf-8')


def test_subscription_post_standing_subscription_cancellation_status(client, subscription, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa_instance.cancellation_requested = True
    sa.registrar_standing_subscription.return_value = sa_instance
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=sentinel_bytes)

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    assert prepped.mock_calls[0][1][0]['subscription']['status'] == 'Cancellation Requested'


def test_subscription_other_methods(client, subscription):
    get_not_allowed(client, subscription['route'])
    put_patch_delete_not_allowed(client, subscription['route'])


# cancellation request

def test_cancel_request_post_invalid_transmission(client, cancel_request, mocker):
    process = mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, side_effect=InvalidTransmissionException)

    # request
    response = client.post(cancel_request['route'], cancel_request['valid_data'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    process.assert_called_once_with(dict_to_querydict(cancel_request['valid_data']), FIELDS_REQUIRED_FROM_PERMA['cancel_request'])


def test_cancel_request_post_subscription_unalterable(client, cancel_request, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=cancel_request['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa_instance.can_be_altered.return_value = False
    sa.registrar_standing_subscription.return_value = sa_instance

    # request
    response = client.post(cancel_request['route'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"can't find any active subscriptions" in response.content
    sa_instance.can_be_altered.assert_called_once()


def test_cancel_request_post_subscription_happy_path(client, cancel_request, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=cancel_request['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa_instance.can_be_altered.return_value = True
    sa.registrar_standing_subscription.return_value = sa_instance
    email = mocker.patch('perma_payments.views.send_admin_email', autospec=True)
    log = mocker.patch('perma_payments.views.logger.info', autospec=True)

    # request
    response = client.post(cancel_request['route'])

    # assertions
    sa_instance.can_be_altered.assert_called_once()
    log.assert_called_once()
    assert email.mock_calls[0][1][1] == settings.DEFAULT_FROM_EMAIL
    assert email.mock_calls[0][2]['template'] == "email/cancel.txt"
    assert email.mock_calls[0][2]['context'] == {
        'registrar': registrar_id,
        'search_url': CS_SUBSCRIPTION_SEARCH_URL[settings.CS_MODE],
        'perma_url': settings.PERMA_URL,
        'registrar_detail_path': settings.REGISTRAR_DETAIL_PATH,
        'registrar_users_path': settings.REGISTRAR_USERS_PATH,
        'merchant_reference_number': sa_instance.subscription_request.reference_number
    }
    sa_instance.save.assert_called_once_with(update_fields=['cancellation_requested'])
    assert response.status_code == 302
    assert response['Location'] == settings.PERMA_SUBSCRIPTION_CANCELLED_REDIRECT_URL


@pytest.mark.django_db
def test_cancel_request_post_subscription_status_actually_updated(client, cancel_request, complete_standing_sa, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=cancel_request['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.registrar_standing_subscription.return_value = complete_standing_sa
    client.post(cancel_request['route'])
    assert complete_standing_sa.cancellation_requested


def test_cancel_request_other_methods(client, cancel_request):
    get_not_allowed(client, cancel_request['route'])
    put_patch_delete_not_allowed(client, cancel_request['route'])


# update_statuses

@pytest.mark.django_db
def test_update_statuses_post_log_in_required(client, update_statuses):
    response = client.post(update_statuses['route'])
    assert response.status_code == 302
    assert response['Location'] == "{}?next={}".format(settings.LOGIN_URL, update_statuses['route'])


@pytest.mark.django_db
def test_update_statuses_post_staff_required(client, non_admin, update_statuses):
    client.force_login(non_admin)
    response = client.post(update_statuses['route'])
    assert response.status_code == 403


@pytest.mark.django_db
def test_update_statuses_post_raises_if_not_found_with_setting(admin_client, update_statuses, complete_standing_sa, settings, mocker):
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.objects.filter.return_value.get.side_effect = ObjectDoesNotExist
    log = mocker.patch('perma_payments.views.logger.error', autospec=True)
    settings.RAISE_IF_SUBSCRIPTION_NOT_FOUND = True
    with pytest.raises(ObjectDoesNotExist):
        admin_client.post(update_statuses['route'], update_statuses["valid_data"])
    log.assert_called


@pytest.mark.django_db
def test_update_statuses_post_doesnt_raise_if_not_found_without_setting(admin_client, update_statuses, complete_standing_sa, settings, mocker):
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.objects.filter.return_value.get.side_effect = ObjectDoesNotExist
    log = mocker.patch('perma_payments.views.logger.error', autospec=True)
    settings.RAISE_IF_SUBSCRIPTION_NOT_FOUND = False
    admin_client.post(update_statuses['route'], update_statuses["valid_data"])
    log.assert_called


@pytest.mark.django_db
def test_update_statuses_post_raises_if_multiple_found_with_setting(admin_client, update_statuses, complete_standing_sa, settings, mocker):
    # mocks
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.objects.filter.return_value.get.side_effect = MultipleObjectsReturned
    log = mocker.patch('perma_payments.views.logger.error', autospec=True)
    settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND = True
    with pytest.raises(MultipleObjectsReturned):
        admin_client.post(update_statuses['route'], update_statuses["valid_data"])
    log.assert_called


@pytest.mark.django_db
def test_update_statuses_post_doesnt_raise_if_multiple_found_without_setting(admin_client, update_statuses, complete_standing_sa, settings, mocker):
    # mocks
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.objects.filter.return_value.get.side_effect = MultipleObjectsReturned
    log = mocker.patch('perma_payments.views.logger.error', autospec=True)
    settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND = False
    admin_client.post(update_statuses['route'], update_statuses["valid_data"])
    log.assert_called


@pytest.mark.django_db
def test_update_statuses_post_statuses_happy_path(admin_client, update_statuses, complete_standing_sa, mocker):
    # mocks
    skip_lines = mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    matching_sa = sa.objects.filter
    matching_sa.return_value.get.return_value = complete_standing_sa
    log_info = mocker.patch('perma_payments.views.logger.info', autospec=True)
    log_error = mocker.patch('perma_payments.views.logger.error', autospec=True)

    # request
    response = admin_client.post(update_statuses['route'], update_statuses["valid_data"])

    # assertions
    skip_lines.mock_calls[0][1][0] == 4  # header lines skipped
    assert matching_sa.call_count == 2
    assert matching_sa.return_value.get.call_count == 2
    matching_sa.assert_any_call(subscription_request__reference_number='ref1')
    matching_sa.assert_any_call(subscription_request__reference_number='ref2')
    assert complete_standing_sa.status == 'Updated'
    log_info.assert_called()
    log_error.assert_not_called()
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"Statuses Updated" in response.content


def test_update_statuses_other_methods(admin_client, update_statuses):
    get_not_allowed(admin_client, update_statuses['route'])
    put_patch_delete_not_allowed(admin_client, update_statuses['route'])

