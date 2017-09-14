from datetime import datetime, timezone
import decimal
import random
import urllib

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import QueryDict

# from hypothesis import given
from hypothesis.strategies import characters, text, integers, booleans, datetimes, dates, decimals, uuids, binary, lists, dictionaries
import pytest

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
    return {
        'route': '/update/',
        'template': 'redirect.html'
    }


@pytest.fixture
def cybersource_callback():
    return {
        'route': '/cybersource-callback/',
        'template': 'redirect.html'
    }


@pytest.fixture
def subscription():
    return {
        'route': '/subscription/',
    }


@pytest.fixture
def cancel_request():
    return {
        'route': '/cancel-request/',
    }


@pytest.fixture
def update_statuses():
    return {
        'route': '/update-statuses/',
    }



#
# TESTS
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
# OMG these are ridiculous. Maybe I should break these views out into smaller functions.......

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
    sa.registrar_standing_subscription.return_value=True
    sa_instance = sa.return_value
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
    sa.registrar_standing_subscription.return_value = False
    sa_instance = sa.return_value
    sa_instance.full_clean.side_effect=ValidationError('oh no!')
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value
    log = mocker.patch('perma_payments.views.logger.warning', autospec=True, return_value=mocker.sentinel.logger)

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
    sa.registrar_standing_subscription.return_value = False
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value
    sr_instance.full_clean.side_effect=ValidationError('oh no!')
    log = mocker.patch('perma_payments.views.logger.warning', autospec=True, return_value=mocker.sentinel.logger)

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
    sa.registrar_standing_subscription.return_value = False
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
    sa.registrar_standing_subscription.return_value = False
    sa_instance = sa.return_value
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
    sa.registrar_standing_subscription.return_value = False
    sa_instance = sa.return_value
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value
    prepped = mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True, return_value=subscribe_redirect_fields)

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

def test_update_post(update):
    pass


def test_update_other_methods(client, update):
    get_not_allowed(client, update['route'])
    put_patch_delete_not_allowed(client, update['route'])


# cybersource_callback

def test_cybersource_callback_post(cybersource_callback):
    pass


def test_cybersource_callback_other_methods(client, cybersource_callback):
    get_not_allowed(client, cybersource_callback['route'])
    put_patch_delete_not_allowed(client, cybersource_callback['route'])


# subscription

def test_subscription_post(subscription):
    pass


def test_subscription_other_methods(client, subscription):
    get_not_allowed(client, subscription['route'])
    put_patch_delete_not_allowed(client, subscription['route'])


# cancel_request

def test_cancel_request_post(cancel_request):
    pass


def test_cancel_request_other_methods(client, cancel_request):
    get_not_allowed(client, cancel_request['route'])
    put_patch_delete_not_allowed(client, cancel_request['route'])


# update_statuses

def test_update_statuses_post(update_statuses):
    pass


def test_update_statuses_other_methods(client, update_statuses):
    get_not_allowed(client, update_statuses['route'])
    put_patch_delete_not_allowed(client, update_statuses['route'])

