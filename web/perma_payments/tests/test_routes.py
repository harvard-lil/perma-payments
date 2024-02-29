"""
These are integration tests covering:

- urls.py,
- view functions in views.py functions, and how they interface with models,
- template rendering

"""

import csv
import io
from datetime import datetime
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, ObjectDoesNotExist, MultipleObjectsReturned
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.timezone import make_aware


import pytest
from pytest_factoryboy import register
from unittest.mock import Mock

from perma_payments.constants import CS_SUBSCRIPTION_SEARCH_URL
from perma_payments.models import (STANDING_STATUSES,
    SubscriptionAgreement, UpdateRequestResponse, ChangeRequestResponse,
    SubscriptionRequestResponse, PurchaseRequestResponse)
from perma_payments.security import InvalidTransmissionException
from perma_payments.views import (FIELDS_REQUIRED_FROM_PERMA,
    FIELDS_REQUIRED_FOR_CYBERSOURCE, FIELDS_REQUIRED_FROM_CYBERSOURCE, redact)


from .factories import (PurchaseRequestFactory, PurchaseRequestResponseFactory,
    SubscriptionRequestFactory, SubscriptionRequestResponseFactory, ChangeRequestFactory, UpdateRequestFactory
)
from .utils import GENESIS, SENTINEL, expected_template_used, get_not_allowed, post_not_allowed, put_patch_delete_not_allowed, dict_to_querydict


register(PurchaseRequestFactory)
register(PurchaseRequestResponseFactory)
register(SubscriptionRequestFactory)
register(SubscriptionRequestResponseFactory)
register(ChangeRequestFactory)
register(UpdateRequestFactory)


#
# FIXTURES
#

# routes

@pytest.fixture
def index():
    return {
        'route': '/',
        'template': 'generic.html'
    }


@pytest.fixture
def purchase():
    data = {
        'route': '/purchase/',
        'template': 'redirect.html',
        'valid_data': {
            'customer_pk': SENTINEL['customer_pk'],
            'customer_type': SENTINEL['customer_type'],
            'amount': SENTINEL['amount'],
            'link_quantity': SENTINEL['link_quantity'],
        }
    }
    for field in FIELDS_REQUIRED_FROM_PERMA['purchase']:
        assert field in data['valid_data']
    return data


@pytest.fixture
def purchase_redirect_fields():
    return {field: field for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['purchase']}


@pytest.fixture
def acknowledge_purchase():
    data = {
        'route': '/acknowledge-purchase/',
        'valid_data': {
            'purchase_pk': SENTINEL['purchase_pk'],
        }
    }
    for field in FIELDS_REQUIRED_FROM_PERMA['acknowledge_purchase']:
        assert field in data['valid_data']
    return data


@pytest.fixture
def purchase_history():
    return {
        'route': '/purchase-history/',
        'valid_data': {
            'customer_pk': SENTINEL['customer_pk'],
            'customer_type': SENTINEL['customer_type'],
        }
    }


@pytest.fixture
def subscribe():
    data = {
        'route': '/subscribe/',
        'template': 'redirect.html',
        'valid_data': {
            'customer_pk': SENTINEL['customer_pk'],
            'customer_type': SENTINEL['customer_type'],
            'amount': SENTINEL['amount'],
            'recurring_amount': SENTINEL['recurring_amount'],
            'recurring_frequency': SENTINEL['recurring_frequency'],
            'recurring_start_date': SENTINEL['date'],
            'link_limit': SENTINEL['link_limit'],
            'link_limit_effective_timestamp': SENTINEL['datetime'].timestamp(),
        }
    }
    for field in FIELDS_REQUIRED_FROM_PERMA['subscribe']:
        assert field in data['valid_data']
    return data


@pytest.fixture
def subscribe_redirect_fields():
    return {field: field for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['subscribe']}


@pytest.fixture
def change():
    data = {
        'route': '/change/',
        'template': 'redirect.html',
        'valid_data': {
            'customer_pk': SENTINEL['customer_pk'],
            'customer_type': SENTINEL['customer_type'],
            'amount': SENTINEL['amount'],
            'recurring_amount': SENTINEL['recurring_amount'],
            'link_limit': SENTINEL['link_limit'],
            'link_limit_effective_timestamp': SENTINEL['datetime'].timestamp()
        }
    }
    for field in FIELDS_REQUIRED_FROM_PERMA['change']:
        assert field in data['valid_data']
    return data


@pytest.fixture
def change_redirect_fields():
    return {field: field for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['change']}


@pytest.fixture
def update():
    data = {
        'route': '/update/',
        'template': 'redirect.html',
        'valid_data': {
            'customer_pk': SENTINEL['customer_pk'],
            'customer_type': SENTINEL['customer_type'],
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
            'req_transaction_uuid': SENTINEL['req_transaction_uuid'],
            'decision': SENTINEL['decision'],
            'reason_code': SENTINEL['reason_code'],
            'message': SENTINEL['message'],
            'payment_token': SENTINEL['payment_token']
        },
        'data_w_invalid_payment_token': {
            'req_transaction_uuid': SENTINEL['req_transaction_uuid'],
            'decision': SENTINEL['decision'],
            'reason_code': SENTINEL['reason_code'],
            'message': SENTINEL['message'],
            'payment_token': SENTINEL['invalid_payment_token']
        }
    }


@pytest.fixture
def subscription():
    return {
        'route': '/subscription/',
        'valid_data': {
            'customer_pk': SENTINEL['customer_pk'],
            'customer_type': SENTINEL['customer_type'],
        }
    }


@pytest.fixture
def cancel_request():
    return {
        'route': '/cancel-request/',
        'valid_data': {
            'customer_pk': SENTINEL['customer_pk'],
            'customer_type': SENTINEL['customer_type'],
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
def broken_update_statuses(broken_status_csv):
    return {
        'route': '/update-statuses/',
        'valid_data': {
            'csv_file': broken_status_csv
        }
    }


# files

@pytest.fixture
def status_csv():
    output = io.StringIO()
    fieldnames = ['Merchant Reference Code', 'Status']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    # This fixture uses statuses with incorrect capitalization, to make sure we can handle that
    writer.writerow({'Merchant Reference Code': 'ref1', 'Status': 'SUPERSEDED'})
    writer.writerow({'Merchant Reference Code': 'ref2', 'Status': 'sUpErSeDeD'})
    return SimpleUploadedFile("csv.csv", bytes(output.getvalue(), 'utf-8'), content_type="text/csv")


@pytest.fixture
def broken_status_csv():
    output = io.StringIO()
    fieldnames = ['Merchant Reference Code', 'Status']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow({'Merchant Reference Code': 'ref1', 'Status': 'asdf'})
    writer.writerow({'Merchant Reference Code': 'ref2', 'Status': 'Superseded'})
    return SimpleUploadedFile("csv.csv", bytes(output.getvalue(), 'utf-8'), content_type="text/csv")


# models

@pytest.fixture
@pytest.mark.django_db
def pending_sa(subscription_request_factory):
    sr = subscription_request_factory()
    return sr.subscription_agreement


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def complete_standing_sa(request, subscription_request_response_factory):
    srr = subscription_request_response_factory(related_request__subscription_agreement__status=request.param)
    sa = srr.subscription_agreement
    assert not sa.cancellation_requested
    return sa


@pytest.fixture
@pytest.mark.django_db
def sa_w_cancellation_requested(complete_standing_sa):
    complete_standing_sa.cancellation_requested = True
    complete_standing_sa.save()
    assert complete_standing_sa.cancellation_requested
    return complete_standing_sa


@pytest.fixture
@pytest.mark.django_db
def canceled_sa(sa_w_cancellation_requested):
    sa_w_cancellation_requested.status = 'Canceled'
    sa_w_cancellation_requested.paid_through = GENESIS
    sa_w_cancellation_requested.save()
    assert sa_w_cancellation_requested.cancellation_requested
    return sa_w_cancellation_requested


@pytest.fixture
@pytest.mark.django_db
def purchase_request(purchase_request_factory):
    return purchase_request_factory()


@pytest.fixture
@pytest.mark.django_db
def subscription_request(subscription_request_factory):
    return subscription_request_factory()


@pytest.fixture
@pytest.mark.django_db
def update_request(update_request_factory):
    return update_request_factory()


@pytest.fixture
@pytest.mark.django_db
def change_request(change_request_factory):
    return change_request_factory()


@pytest.fixture
@pytest.mark.django_db
def get_prr_for_user(purchase_request_response_factory):
    def factory(customer_pk, customer_type, inform_perma=True):
        return purchase_request_response_factory(
            related_request__customer_pk=customer_pk,
            related_request__customer_type=customer_type,
            inform_perma=inform_perma
        )
    return factory



@pytest.fixture()
@pytest.mark.django_db
def non_admin():
    return User.objects.create_user('joe')


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


# purchase

def test_purchase_post_invalid_perma_transmission(client, purchase, mocker):
    # mocks
    process = mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, side_effect=InvalidTransmissionException)
    pr = mocker.patch('perma_payments.views.PurchaseRequest', autospec=True)
    pr_instance = pr.return_value

    # request
    response = client.post(purchase['route'], purchase['valid_data'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    process.assert_called_once_with(dict_to_querydict(purchase['valid_data']), FIELDS_REQUIRED_FROM_PERMA['purchase'])
    assert not pr_instance.save.called


def test_purchase_post_pr_validation_fails(client, purchase, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=purchase['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    pr = mocker.patch('perma_payments.views.PurchaseRequest', autospec=True)
    pr_instance = pr.return_value
    pr_instance.full_clean.side_effect=ValidationError('oh no!')
    log = mocker.patch('perma_payments.views.logger.warning', autospec=True)

    # request
    response = client.post(purchase['route'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    assert pr_instance.full_clean.call_count == 1
    assert not pr_instance.save.called
    assert log.call_count == 1


def test_purchase_post_pr_validated_and_saved_correctly(client, purchase, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=purchase['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    pr = mocker.patch('perma_payments.views.PurchaseRequest', autospec=True)
    pr_instance = pr.return_value

    # request
    response = client.post(purchase['route'])

    # assertions
    assert response.status_code == 200
    pr.assert_called_once_with(
        customer_pk=purchase['valid_data']['customer_pk'],
        customer_type=purchase['valid_data']['customer_type'],
        amount=purchase['valid_data']['amount'],
        link_quantity=purchase['valid_data']['link_quantity'],
    )
    assert pr_instance.full_clean.call_count == 1
    assert pr_instance.save.call_count == 1


def test_purchase_post_data_prepped_correctly(client, purchase, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=purchase['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    pr = mocker.patch('perma_payments.views.PurchaseRequest', autospec=True)
    pr_instance = pr.return_value
    prepped = mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True)

    # request
    response = client.post(purchase['route'])

    # assertions
    assert response.status_code == 200
    fields_to_prep = {
        'access_key': settings.CS_ACCESS_KEY,
        'amount': pr_instance.amount,
        'currency': pr_instance.currency,
        'locale': pr_instance.locale,
        'payment_method': pr_instance.payment_method,
        'profile_id': settings.CS_PROFILE_ID,
        'reference_number': pr_instance.reference_number,
        'signed_date_time': pr_instance.get_formatted_datetime(),
        'transaction_type': pr_instance.transaction_type,
        'transaction_uuid': pr_instance.transaction_uuid,
    }
    prepped.assert_called_once_with(fields_to_prep)
    for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['purchase']:
        assert field in fields_to_prep


def test_purchase_post_redirect_form_populated_correctly(client, purchase, purchase_redirect_fields, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=purchase['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    mocker.patch('perma_payments.views.PurchaseRequest', autospec=True)
    mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True, return_value=purchase_redirect_fields)

    # request
    response = client.post(purchase['route'])

    # assertions
    assert response.status_code == 200
    assert response.context['fields_to_post'] == purchase_redirect_fields
    context = list(response.context.keys())
    for field in ['fields_to_post', 'post_to_url']:
        assert field in context
    expected_template_used(response, 'redirect.html')
    for field in purchase_redirect_fields:
        assert bytes('<input type="hidden" name="{0}" value="{0}">'.format(field), 'utf-8') in response.content


def test_purchase_other_methods(client, purchase):
    put_patch_delete_not_allowed(client, purchase['route'])


def test_purchase_get(client, purchase, index):
    response = client.get(purchase['route'])
    assert response.status_code == 200
    expected_template_used(response, index['template'])


# acknowledge-purchase

@pytest.mark.django_db
def test_acknowledge_purchase(client, acknowledge_purchase, purchase_request_response_factory, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=acknowledge_purchase['valid_data'])
    prr = purchase_request_response_factory(
        id=SENTINEL['purchase_pk'],
        inform_perma=True
    )
    assert not prr.perma_acknowledged_at

    # request
    response = client.post(acknowledge_purchase['route'])

    # assertions
    assert response.status_code == 200
    prr.refresh_from_db()
    assert prr.perma_acknowledged_at


@pytest.mark.django_db
def test_acknowledge_unacknowledgeable_purchase(client, acknowledge_purchase, purchase_request_response_factory, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=acknowledge_purchase['valid_data'])
    prr = purchase_request_response_factory(
        id=SENTINEL['purchase_pk'],
        inform_perma=False
    )
    assert not prr.perma_acknowledged_at

    # request
    response = client.post(acknowledge_purchase['route'])

    # assertions
    assert response.status_code == 400


@pytest.mark.django_db
def test_acknowledge_already_acknowledged_purchase(client, acknowledge_purchase, purchase_request_response_factory, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=acknowledge_purchase['valid_data'])
    prr = purchase_request_response_factory(
        id=SENTINEL['purchase_pk'],
        inform_perma=True,
        perma_acknowledged_at=GENESIS
    )
    assert prr.perma_acknowledged_at == GENESIS

    # request
    response = client.post(acknowledge_purchase['route'])

    # assertions
    assert response.status_code == 400
    prr.refresh_from_db()
    assert prr.perma_acknowledged_at == GENESIS


@pytest.mark.django_db
def test_acknowledge_nonexistent_purchase(client, acknowledge_purchase, purchase_request_response_factory, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=acknowledge_purchase['valid_data'])
    prr = purchase_request_response_factory(
        id=SENTINEL['purchase_pk'] + 1,
        inform_perma=True
    )
    assert not prr.perma_acknowledged_at

    # request
    response = client.post(acknowledge_purchase['route'])

    # assertions
    assert response.status_code == 400
    prr.refresh_from_db()
    assert not prr.perma_acknowledged_at


def test_acknowledge_purchase_other_methods(client, acknowledge_purchase):
    get_not_allowed(client, acknowledge_purchase['route'])
    put_patch_delete_not_allowed(client, acknowledge_purchase['route'])


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
    sa.customer_standing_subscription.return_value=sa_instance
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value

    # request
    response = client.post(subscribe['route'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b'already have a subscription' in response.content
    sa.customer_standing_subscription.assert_called_once_with(subscribe['valid_data']['customer_pk'], subscribe['valid_data']['customer_type'])
    assert not sa_instance.save.called
    assert not sr_instance.save.called


def test_subscribe_post_sa_validation_fails(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.customer_standing_subscription.return_value = None
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
    assert sa_instance.full_clean.call_count == 1
    assert not sa_instance.save.called
    assert not sr_instance.save.called
    assert log.call_count == 1


def test_subscribe_post_sr_validation_fails(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.customer_standing_subscription.return_value = None
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
    assert sr_instance.full_clean.call_count == 1
    assert not sr_instance.save.called
    assert log.call_count == 1


def test_subscribe_post_sa_and_sr_validated_and_saved_correctly(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.customer_standing_subscription.return_value = None
    sa_instance = sa.return_value
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value

    # request
    response = client.post(subscribe['route'])

    # assertions
    assert response.status_code == 200
    sa.assert_called_once_with(
        customer_pk=subscribe['valid_data']['customer_pk'],
        customer_type=subscribe['valid_data']['customer_type'],
        status='Pending'
    )
    assert sa_instance.full_clean.call_count == 1
    assert sa_instance.save.call_count == 1
    sr.assert_called_once_with(
        subscription_agreement=sa_instance,
        amount=subscribe['valid_data']['amount'],
        recurring_amount=subscribe['valid_data']['recurring_amount'],
        recurring_frequency=subscribe['valid_data']['recurring_frequency'],
        recurring_start_date=subscribe['valid_data']['recurring_start_date'],
        link_limit=subscribe['valid_data']['link_limit'],
        link_limit_effective_timestamp=make_aware(datetime.fromtimestamp(subscribe['valid_data']['link_limit_effective_timestamp']))
    )
    assert sr_instance.full_clean.call_count == 1
    assert sr_instance.save.call_count == 1


def test_subscribe_post_data_prepped_correctly(client, subscribe, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscribe['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.customer_standing_subscription.return_value = None
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
    sa.customer_standing_subscription.return_value = None
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
    put_patch_delete_not_allowed(client, subscribe['route'])


def test_subscribe_get(client, subscribe, index):
    response = client.get(subscribe['route'])
    assert response.status_code == 200
    expected_template_used(response, index['template'])


# change

def test_change_post_invalid_perma_transmission(client, change, mocker):
    # mocks
    process = mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, side_effect=InvalidTransmissionException)
    cr = mocker.patch('perma_payments.views.ChangeRequest', autospec=True)
    cr_instance = cr.return_value

    # request
    response = client.post(change['route'], change['valid_data'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    process.assert_called_once_with(dict_to_querydict(change['valid_data']), FIELDS_REQUIRED_FROM_PERMA['change'])
    assert not cr_instance.save.called


@pytest.mark.django_db
def test_change_post_no_standing_subscription(client, change, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=change['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.customer_standing_subscription.return_value = None
    cr = mocker.patch('perma_payments.views.ChangeRequest', autospec=True)
    cr_instance = cr.return_value

    # request
    response = client.post(change['route'], change['valid_data'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"can't find any active subscriptions" in response.content
    sa.customer_standing_subscription.assert_called_once_with(change['valid_data']['customer_pk'], change['valid_data']['customer_type'])
    assert not cr_instance.save.called


def test_change_post_subscription_unalterable(client, change, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=change['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa_instance.can_be_altered.return_value = False
    sa.customer_standing_subscription.return_value = sa_instance
    cr = mocker.patch('perma_payments.views.ChangeRequest', autospec=True)
    cr_instance = cr.return_value

    # request
    response = client.post(change['route'], change['valid_data'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"can't find any active subscriptions" in response.content
    assert sa_instance.can_be_altered.call_count == 1
    assert not cr_instance.save.called


@pytest.mark.django_db
def test_change_post_cr_validation_fails(client, change, complete_standing_sa, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=change['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=complete_standing_sa
    )
    cr = mocker.patch('perma_payments.views.ChangeRequest', autospec=True)
    cr_instance = cr.return_value
    cr_instance.full_clean.side_effect=ValidationError('oh no!')
    log = mocker.patch('perma_payments.views.logger.warning', autospec=True)

    # request
    response = client.post(change['route'])

    # assertions
    assert response.status_code == 400
    expected_template_used(response, 'generic.html')
    assert b'Bad Request' in response.content
    assert cr_instance.full_clean.call_count == 1
    assert not cr_instance.save.called
    assert log.call_count == 1


@pytest.mark.django_db
def test_change_post_cr_validated_and_saved_correctly(client, change, complete_standing_sa, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=change['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=complete_standing_sa
    )
    cr = mocker.patch('perma_payments.views.ChangeRequest', autospec=True)
    cr_instance = cr.return_value

    # request
    response = client.post(change['route'])

    # assertions
    assert response.status_code == 200
    cr.assert_called_once_with(
        subscription_agreement=complete_standing_sa,
        amount=change['valid_data']['amount'],
        recurring_amount=change['valid_data']['recurring_amount'],
        link_limit=change['valid_data']['link_limit'],
        link_limit_effective_timestamp=make_aware(datetime.fromtimestamp(change['valid_data']['link_limit_effective_timestamp']))
    )
    assert cr_instance.full_clean.call_count == 1
    assert cr_instance.save.call_count == 1


def test_change_post_data_prepped_correctly(client, change, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=change['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa.customer_standing_subscription.return_value = sa_instance
    sr = mocker.patch('perma_payments.views.SubscriptionRequest', autospec=True)
    sr_instance = sr.return_value
    srr = mocker.patch('perma_payments.views.SubscriptionRequestResponse', autospec=True)
    srr_instance = srr.return_value
    sa_instance.subscription_request = sr_instance
    sr_instance.subscription_request_response = srr_instance
    cr = mocker.patch('perma_payments.views.ChangeRequest', autospec=True)
    cr_instance = cr.return_value
    prepped = mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True)

    # request
    response = client.post(change['route'])

    # assertions
    assert response.status_code == 200
    fields_to_prep = {
        'access_key': settings.CS_ACCESS_KEY,
        'allow_payment_token_update': 'true',
        'amount': cr_instance.amount,
        'currency': cr_instance.currency,
        'locale': cr_instance.locale,
        'payment_method': cr_instance.payment_method,
        'payment_token': srr_instance.payment_token,
        'profile_id': settings.CS_PROFILE_ID,
        'recurring_amount': cr_instance.recurring_amount,
        'reference_number': sr_instance.reference_number,
        'signed_date_time': cr_instance.get_formatted_datetime(),
        'transaction_type': cr_instance.transaction_type,
        'transaction_uuid': cr_instance.transaction_uuid,
    }
    prepped.assert_called_once_with(fields_to_prep)
    for field in FIELDS_REQUIRED_FOR_CYBERSOURCE['change']:
        assert field in fields_to_prep


def test_change_post_redirect_form_populated_correctly(client, change, change_redirect_fields, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=change['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription
    )
    mocker.patch('perma_payments.views.ChangeRequest', autospec=True)
    mocker.patch('perma_payments.views.prep_for_cybersource', autospec=True, return_value=change_redirect_fields)


    # request
    response = client.post(change['route'])

    # assertions
    assert response.status_code == 200
    assert response.context['fields_to_post'] == change_redirect_fields
    context = list(response.context.keys())
    for field in ['fields_to_post', 'post_to_url']:
        assert field in context
    expected_template_used(response, 'redirect.html')
    for field in change_redirect_fields:
        assert bytes('<input type="hidden" name="{0}" value="{0}">'.format(field), 'utf-8') in response.content


def test_change_other_methods(client, change):
    get_not_allowed(client, change['route'])
    put_patch_delete_not_allowed(client, change['route'])


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
    sa.customer_standing_subscription.return_value = None
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value

    # request
    response = client.post(update['route'], update['valid_data'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"can't find any active subscriptions" in response.content
    sa.customer_standing_subscription.assert_called_once_with(update['valid_data']['customer_pk'], update['valid_data']['customer_type'])
    assert not ur_instance.save.called


def test_update_post_subscription_unalterable(client, update, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa_instance.can_be_altered.return_value = False
    sa.customer_standing_subscription.return_value = sa_instance
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value

    # request
    response = client.post(update['route'], update['valid_data'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"can't find any active subscriptions" in response.content
    assert sa_instance.can_be_altered.call_count == 1
    assert not ur_instance.save.called


@pytest.mark.django_db
def test_update_post_ur_validation_fails(client, update, complete_standing_sa, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=complete_standing_sa
    )
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
    assert ur_instance.full_clean.call_count == 1
    assert not ur_instance.save.called
    assert log.call_count == 1


@pytest.mark.django_db
def test_update_post_ur_validated_and_saved_correctly(client, update, complete_standing_sa, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=complete_standing_sa
    )
    ur = mocker.patch('perma_payments.views.UpdateRequest', autospec=True)
    ur_instance = ur.return_value

    # request
    response = client.post(update['route'])

    # assertions
    assert response.status_code == 200
    ur.assert_called_once_with(
        subscription_agreement=complete_standing_sa
    )
    assert ur_instance.full_clean.call_count == 1
    assert ur_instance.save.call_count == 1


def test_update_post_data_prepped_correctly(client, update, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=update['valid_data'])
    mocker.patch('perma_payments.views.transaction.atomic', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa_instance = sa.return_value
    sa.customer_standing_subscription.return_value = sa_instance
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
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription
    )
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
def test_cybersource_callback_post_update_request(client, cybersource_callback, update_request, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['valid_data'])
    get_request = mocker.patch(
        'perma_payments.views.OutgoingTransaction.objects.get',
        autospec=True,
        return_value = update_request
    )
    r = mocker.patch('perma_payments.views.Response', autospec=True)

    # request
    response = client.post(cybersource_callback['route'], cybersource_callback['valid_data'])

    # assertions
    get_request.assert_called_once_with(transaction_uuid=cybersource_callback['valid_data']['req_transaction_uuid'])
    r.save_new_with_encrypted_full_response.assert_called_once_with(
        UpdateRequestResponse,
        dict_to_querydict(cybersource_callback['valid_data']),
        {
            'related_request': update_request,
            'decision': cybersource_callback['valid_data']['decision'],
            'reason_code': cybersource_callback['valid_data']['reason_code'],
            'message': cybersource_callback['valid_data']['message']
        }
    )
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b'OK' in response.content


@pytest.mark.django_db
def test_cybersource_callback_post_change_request(client, cybersource_callback, change_request, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['valid_data'])
    get_request = mocker.patch(
        'perma_payments.views.OutgoingTransaction.objects.get',
        autospec=True,
        return_value = change_request
    )
    mocker.patch.object(change_request.subscription_agreement, 'update_after_cs_decision')
    r = mocker.patch('perma_payments.views.Response', autospec=True)

    # request
    response = client.post(cybersource_callback['route'], cybersource_callback['valid_data'])

    # assertions
    get_request.assert_called_once_with(transaction_uuid=cybersource_callback['valid_data']['req_transaction_uuid'])
    r.save_new_with_encrypted_full_response.assert_called_once_with(
        ChangeRequestResponse,
        dict_to_querydict(cybersource_callback['valid_data']),
        {
            'related_request': change_request,
            'decision': cybersource_callback['valid_data']['decision'],
            'reason_code': cybersource_callback['valid_data']['reason_code'],
            'message': cybersource_callback['valid_data']['message']
        }
    )
    change_request.subscription_agreement.update_after_cs_decision.assert_called_once_with(
        change_request,
        cybersource_callback['valid_data']['decision'],
        redact(cybersource_callback['valid_data'])
    )
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b'OK' in response.content


@pytest.mark.django_db
def test_cybersource_callback_post_subscription_request(client, cybersource_callback, pending_sa, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['valid_data'])
    get_request = mocker.patch(
        'perma_payments.views.OutgoingTransaction.objects.get',
        autospec=True,
        return_value = pending_sa.subscription_request
    )
    mocker.patch.object(pending_sa, 'update_after_cs_decision')
    r = mocker.patch('perma_payments.views.Response', autospec=True)

    # request
    response = client.post(cybersource_callback['route'], cybersource_callback['valid_data'])

    # assertions
    get_request.assert_called_once_with(transaction_uuid=cybersource_callback['valid_data']['req_transaction_uuid'])
    r.save_new_with_encrypted_full_response.assert_called_once_with(
        SubscriptionRequestResponse,
        dict_to_querydict(cybersource_callback['valid_data']),
        {
            'related_request': pending_sa.subscription_request,
            'decision': cybersource_callback['valid_data']['decision'],
            'reason_code': cybersource_callback['valid_data']['reason_code'],
            'message': cybersource_callback['valid_data']['message'],
            'payment_token': cybersource_callback['valid_data']['payment_token']
        }
    )
    pending_sa.update_after_cs_decision.assert_called_once_with(
        pending_sa.subscription_request,
        cybersource_callback['valid_data']['decision'],
        redact(cybersource_callback['valid_data'])
    )
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b'OK' in response.content


@pytest.mark.django_db
def test_cybersource_callback_payment_token_invalid(client, cybersource_callback, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['data_w_invalid_payment_token'])
    mocker.patch('perma_payments.views.OutgoingTransaction', autospec=True)
    mocker.patch('perma_payments.views.isinstance', side_effect=[False, False, True])  # force isinstance to return True third, for SubscriptionRequest
    mocker.patch('perma_payments.views.Response', autospec=True)
    log = mocker.patch('perma_payments.views.logger.error', autospec=True)

    client.post(cybersource_callback['route'], cybersource_callback['data_w_invalid_payment_token'])

    assert log.call_count == 1


@pytest.mark.django_db
def test_cybersource_callback_post_purchase_request(client, cybersource_callback, purchase_request_response, mocker):
    mocker.patch('perma_payments.views.process_cybersource_transmission', autospec=True, return_value=cybersource_callback['valid_data'])
    purchase_request = purchase_request_response.related_request
    get_request = mocker.patch(
        'perma_payments.views.OutgoingTransaction.objects.get',
        autospec=True,
        return_value = purchase_request
    )
    r = mocker.patch('perma_payments.views.Response', autospec=True)
    r.save_new_with_encrypted_full_response.return_value = purchase_request_response
    purchase_request_response.act_on_cs_decision = Mock()

    # request
    response = client.post(cybersource_callback['route'], cybersource_callback['valid_data'])

    # assertions
    get_request.assert_called_once_with(transaction_uuid=cybersource_callback['valid_data']['req_transaction_uuid'])
    r.save_new_with_encrypted_full_response.assert_called_once_with(
        PurchaseRequestResponse,
        dict_to_querydict(cybersource_callback['valid_data']),
        {
            'related_request': purchase_request,
            'decision': cybersource_callback['valid_data']['decision'],
            'reason_code': cybersource_callback['valid_data']['reason_code'],
            'message': cybersource_callback['valid_data']['message'],
        }
    )
    purchase_request_response.act_on_cs_decision.assert_called_once_with(
        redact(cybersource_callback['valid_data'])
    )
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b'OK' in response.content


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


@pytest.mark.django_db
def test_subscription_post_no_standing_subscription(client, subscription, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    sa = mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=None
    )
    d = mocker.patch('perma_payments.views.datetime', autospec=True)
    d.utcnow.return_value.timestamp.return_value = mocker.sentinel.timestamp
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=SENTINEL['bytes'])

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    assert d.utcnow.return_value.timestamp.call_count == 1
    sa.assert_called_once_with(subscription['valid_data']['customer_pk'], subscription['valid_data']['customer_type'])
    prepped.assert_called_once_with({
        'customer_pk': subscription['valid_data']['customer_pk'],
        'customer_type': subscription['valid_data']['customer_type'],
        'subscription': None,
        'timestamp': mocker.sentinel.timestamp,
        'purchases': []
    })
    r = response.json()
    assert r and list(r.keys()) == ['encrypted_data']
    assert r['encrypted_data'] == SENTINEL['bytes'].decode('utf-8')


@pytest.mark.django_db
def test_subscription_post_standard_standing_subscription(client, subscription, complete_standing_sa, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    sa = mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=complete_standing_sa
    )
    d = mocker.patch('perma_payments.views.datetime', autospec=True)
    d.utcnow.return_value.timestamp.return_value = mocker.sentinel.timestamp
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=SENTINEL['bytes'])

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    sa.assert_called_once_with(subscription['valid_data']['customer_pk'], subscription['valid_data']['customer_type'])
    prepped.assert_called_once_with({
        'customer_pk': subscription['valid_data']['customer_pk'],
        'customer_type': subscription['valid_data']['customer_type'],
        'subscription': {
            'link_limit': complete_standing_sa.current_link_limit,
            'link_limit_effective_timestamp': complete_standing_sa.current_link_limit_effective_timestamp,
            'rate': complete_standing_sa.current_rate,
            'frequency': complete_standing_sa.current_frequency,
            'status': complete_standing_sa.status,
            'paid_through': complete_standing_sa.paid_through,
            'reference_number': complete_standing_sa.subscription_request.reference_number,
        },
        'timestamp': mocker.sentinel.timestamp,
        'purchases': []
    })
    r = response.json()
    assert r and list(r.keys()) == ['encrypted_data']
    assert r['encrypted_data'] == SENTINEL['bytes'].decode('utf-8')


@pytest.mark.django_db
def test_subscription_post_standing_subscription_cancellation_requested(client, subscription, sa_w_cancellation_requested, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=sa_w_cancellation_requested
    )
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=SENTINEL['bytes'])

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    assert prepped.mock_calls[0][1][0]['subscription']['status'] == 'Cancellation Requested'


@pytest.mark.django_db
def test_subscription_post_standing_subscription_canceled(client, subscription, canceled_sa, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=canceled_sa
    )
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=SENTINEL['bytes'])

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    assert prepped.mock_calls[0][1][0]['subscription']['status'] == 'Canceled'


@pytest.mark.django_db
def test_subscription_single_purchase_to_acknowledge(client, subscription, get_prr_for_user, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=SENTINEL['bytes'])
    prr = get_prr_for_user(SENTINEL['customer_pk'], SENTINEL['customer_type'])

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    purchases = prepped.mock_calls[0][1][0]['purchases']
    assert purchases == [{
        "id": prr.id,
        "link_quantity": prr.related_request.link_quantity
    }]


@pytest.mark.django_db
def test_subscription_multiple_purchases_to_acknowledge(client, subscription, get_prr_for_user, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=subscription['valid_data'])
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=SENTINEL['bytes'])
    prr1 = get_prr_for_user(SENTINEL['customer_pk'], SENTINEL['customer_type'])
    prr2 = get_prr_for_user(SENTINEL['customer_pk'], SENTINEL['customer_type'])
    get_prr_for_user(SENTINEL['customer_pk'], SENTINEL['customer_type'], inform_perma=False)

    # request
    response = client.post(subscription['route'])

    assert response.status_code == 200
    purchases = prepped.mock_calls[0][1][0]['purchases']
    assert purchases == [{
        "id": prr1.id,
        "link_quantity": prr1.related_request.link_quantity
    },{
        "id": prr2.id,
        "link_quantity": prr2.related_request.link_quantity
    }]


def test_subscription_other_methods(client, subscription):
    get_not_allowed(client, subscription['route'])
    put_patch_delete_not_allowed(client, subscription['route'])


# purchase history

@pytest.mark.django_db
def test_single_purchase_in_history(client, purchase_history, get_prr_for_user, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=purchase_history['valid_data'])
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=SENTINEL['bytes'])
    prr = get_prr_for_user(SENTINEL['customer_pk'], SENTINEL['customer_type'])

    # request
    response = client.post(purchase_history['route'])

    assert response.status_code == 200
    purchase_history = prepped.mock_calls[0][1][0]['purchase_history']
    assert purchase_history == [{
        "id": prr.id,
        "link_quantity": prr.related_request.link_quantity,
        "date": prr.related_request.request_datetime,
        "reference_number": prr.related_request.reference_number
    }]


@pytest.mark.django_db
def test_multiple_purchases_in_history(client, purchase_history, get_prr_for_user, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=purchase_history['valid_data'])
    prepped = mocker.patch('perma_payments.views.prep_for_perma', autospec=True, return_value=SENTINEL['bytes'])
    prr1 = get_prr_for_user(SENTINEL['customer_pk'], SENTINEL['customer_type'])
    prr2 = get_prr_for_user(SENTINEL['customer_pk'], SENTINEL['customer_type'])
    get_prr_for_user(SENTINEL['customer_pk'], SENTINEL['customer_type'], inform_perma=False)

    # request
    response = client.post(purchase_history['route'])

    assert response.status_code == 200
    purchase_history = prepped.mock_calls[0][1][0]['purchase_history']
    assert purchase_history == [{
        "id": prr1.id,
        "link_quantity": prr1.related_request.link_quantity,
        "date": prr1.related_request.request_datetime,
        "reference_number": prr1.related_request.reference_number
    },{
        "id": prr2.id,
        "link_quantity": prr2.related_request.link_quantity,
        "date": prr2.related_request.request_datetime,
        "reference_number": prr2.related_request.reference_number
    }]


def test_purchase_history_other_methods(client, purchase_history):
    get_not_allowed(client, purchase_history['route'])
    put_patch_delete_not_allowed(client, purchase_history['route'])


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


@pytest.mark.django_db
def test_cancel_request_post_subscription_unalterable(client, cancel_request, complete_standing_sa, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=cancel_request['valid_data'])
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=complete_standing_sa
    )
    can_be_altered = mocker.patch.object(complete_standing_sa, 'can_be_altered', return_value=False)

    # request
    response = client.post(cancel_request['route'])

    # assertions
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"can't find any active subscriptions" in response.content
    assert can_be_altered.call_count == 1


@pytest.mark.django_db
def test_cancel_request_post_subscription_happy_path(client, cancel_request, complete_standing_sa, mocker):
    # mocks
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=cancel_request['valid_data'])
    mocker.patch(
        'perma_payments.views.SubscriptionAgreement.customer_standing_subscription',
        spec_set=SubscriptionAgreement.customer_standing_subscription,
        return_value=complete_standing_sa
    )
    can_be_altered = mocker.patch.object(complete_standing_sa, 'can_be_altered', return_value=True)
    email = mocker.patch('perma_payments.views.send_self_email', autospec=True)
    log = mocker.patch('perma_payments.views.logger.info', autospec=True)

    # request
    response = client.post(cancel_request['route'])

    # assertions
    assert can_be_altered.call_count == 1
    assert log.call_count == 1
    assert email.mock_calls[0][2]['template'] == "email/cancel.txt"
    assert email.mock_calls[0][2]['context'] == {
        'customer_pk': cancel_request['valid_data']['customer_pk'],
        'customer_type': cancel_request['valid_data']['customer_type'],
        'search_url': CS_SUBSCRIPTION_SEARCH_URL[settings.CS_MODE],
        'perma_url': settings.PERMA_URL,
        'individual_detail_path': settings.INDIVIDUAL_DETAIL_PATH,
        'registrar_detail_path': settings.REGISTRAR_DETAIL_PATH,
        'registrar_users_path': settings.REGISTRAR_USERS_PATH,
        'merchant_reference_number': complete_standing_sa.subscription_request.reference_number
    }
    assert complete_standing_sa.cancellation_requested
    assert response.status_code == 302
    assert response['Location'] == settings.PERMA_SUBSCRIPTION_CANCELED_REDIRECT_URL


@pytest.mark.django_db
def test_cancel_request_post_subscription_status_actually_updated(client, cancel_request, complete_standing_sa, mocker):
    mocker.patch('perma_payments.views.process_perma_transmission', autospec=True, return_value=cancel_request['valid_data'])
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.customer_standing_subscription.return_value = complete_standing_sa
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
def test_update_statuses_post_alerts_if_not_found_with_setting(admin_client, update_statuses, settings, mocker):
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.objects.filter.return_value.get.side_effect = ObjectDoesNotExist
    log = mocker.patch('perma_payments.views.logger.log', autospec=True)
    settings.RAISE_IF_SUBSCRIPTION_NOT_FOUND = True
    admin_client.post(update_statuses['route'], update_statuses["valid_data"])
    assert log.call_count == 2
    for call in log.call_args_list:
        assert call[0][0] == logging.ERROR


@pytest.mark.django_db
def test_update_statuses_post_doesnt_alert_if_not_found_without_setting(admin_client, update_statuses, settings, mocker):
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.objects.filter.return_value.get.side_effect = ObjectDoesNotExist
    log = mocker.patch('perma_payments.views.logger.log', autospec=True)
    settings.RAISE_IF_SUBSCRIPTION_NOT_FOUND = False
    admin_client.post(update_statuses['route'], update_statuses["valid_data"])
    assert log.call_count == 2
    for call in log.call_args_list:
        assert call[0][0] == logging.INFO


@pytest.mark.django_db
def test_update_statuses_post_alerts_if_multiple_found_with_setting(admin_client, update_statuses, settings, mocker):
    # mocks
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.objects.filter.return_value.get.side_effect = MultipleObjectsReturned
    log = mocker.patch('perma_payments.views.logger.log', autospec=True)
    settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND = True
    admin_client.post(update_statuses['route'], update_statuses["valid_data"])
    assert log.call_count == 2
    for call in log.call_args_list:
        assert call[0][0] == logging.ERROR


@pytest.mark.django_db
def test_update_statuses_post_doesnt_alert_if_multiple_found_without_setting(admin_client, update_statuses, settings, mocker):
    # mocks
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    sa.objects.filter.return_value.get.side_effect = MultipleObjectsReturned
    log = mocker.patch('perma_payments.views.logger.log', autospec=True)
    settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND = False
    admin_client.post(update_statuses['route'], update_statuses["valid_data"])
    assert log.call_count == 2
    for call in log.call_args_list:
        assert call[0][0] == logging.INFO


@pytest.mark.django_db
def test_update_statuses_post_rejects_invalid(admin_client, broken_update_statuses, complete_standing_sa, mocker):
    # mocks
    mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    matching_sa = sa.objects.filter
    matching_sa.return_value.get.return_value = complete_standing_sa
    info_log = mocker.patch('perma_payments.views.logger.info', autospec=True)

    # request
    with pytest.raises(ValidationError):
        admin_client.post(broken_update_statuses['route'], broken_update_statuses["valid_data"])
    assert info_log.call_count == 0


@pytest.mark.django_db
def test_update_statuses_post_statuses_happy_path(admin_client, update_statuses, complete_standing_sa, mocker):
    # mocks
    skip_lines = mocker.patch('perma_payments.views.skip_lines', autospec=True)
    sa = mocker.patch('perma_payments.views.SubscriptionAgreement', autospec=True)
    matching_sa = sa.objects.filter
    matching_sa.return_value.get.return_value = complete_standing_sa
    log = mocker.patch('perma_payments.views.logger.log', autospec=True)
    info_log = mocker.patch('perma_payments.views.logger.info', autospec=True)

    # request
    response = admin_client.post(update_statuses['route'], update_statuses["valid_data"])

    # assertions
    skip_lines.mock_calls[0][1][0] == 4  # header lines skipped
    assert matching_sa.call_count == 2
    assert matching_sa.return_value.get.call_count == 2
    matching_sa.assert_any_call(subscription_request__reference_number='ref1')
    matching_sa.assert_any_call(subscription_request__reference_number='ref2')
    assert complete_standing_sa.status == 'Superseded'
    # this is how we log errors
    assert not log.called
    # this is how we log successes
    assert info_log.call_count == 2
    assert response.status_code == 200
    expected_template_used(response, 'generic.html')
    assert b"Statuses Updated" in response.content


def test_update_statuses_other_methods(admin_client, update_statuses):
    get_not_allowed(admin_client, update_statuses['route'])
    put_patch_delete_not_allowed(admin_client, update_statuses['route'])

