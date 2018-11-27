import datetime
from dateutil.relativedelta import relativedelta
from pytz import timezone
import random

from django.apps import apps
from django.conf import settings
from django.http import QueryDict

import pytest

from perma_payments.constants import CS_DECISIONS
from perma_payments.models import (STANDING_STATUSES, REFERENCE_NUMBER_PREFIX,
    RN_SET, generate_reference_number, SubscriptionAgreement, SubscriptionRequest,
    SubscriptionRequestResponse, UpdateRequest, UpdateRequestResponse,
    OutgoingTransaction, Response)

from .utils import GENESIS, SENTINEL, absent_required_fields_raise_validation_error, autopopulated_fields_present


#
# FIXTURES
#

# Perhaps these all should be generated via Factory Boy.
# For unit testing models, though, it's probably better not to introduce that extra layer

@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def standing_sa(request):
    sa = SubscriptionAgreement(
        customer_pk=SENTINEL['customer_pk'],
        customer_type=SENTINEL['customer_type'],
        status=request.param
    )
    sa.save()
    return sa


@pytest.fixture(params=[status[0] for status in SubscriptionAgreement._meta.get_field('status').choices if status[0] not in STANDING_STATUSES])
@pytest.mark.django_db
def not_standing_sa(request):
    sa = SubscriptionAgreement(
        customer_pk=SENTINEL['customer_pk'],
        customer_type=SENTINEL['customer_type'],
        status=request.param
    )
    sa.save()
    return sa


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def multiple_standing_sa(request):
    sa1 = SubscriptionAgreement(
        customer_pk=SENTINEL['customer_pk'],
        customer_type=SENTINEL['customer_type'],
        status=request.param
    )
    sa1.save()
    sa2 = SubscriptionAgreement(
        customer_pk=SENTINEL['customer_pk'],
        customer_type=SENTINEL['customer_type'],
        status=request.param
    )
    sa2.save()
    return sa1


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def standing_sa_cancellation_requested(request):
    sa = SubscriptionAgreement(
        customer_pk=SENTINEL['customer_pk'],
        customer_type=SENTINEL['customer_type'],
        status=request.param,
        cancellation_requested=True
    )
    sa.save()
    return sa


@pytest.fixture()
@pytest.mark.django_db
def complete_pending_sa():
    sa = SubscriptionAgreement(
        customer_pk=SENTINEL['customer_pk'],
        customer_type=SENTINEL['customer_type'],
        status='Pending'
    )
    sa.save()
    sr = SubscriptionRequest(
        subscription_agreement=sa,
        amount=SENTINEL['amount'],
        recurring_amount=SENTINEL['recurring_amount'],
        recurring_start_date=GENESIS,
        recurring_frequency=SENTINEL['recurring_frequency'],
        link_limit=SENTINEL['link_limit']
    )
    sr.save()
    return sa


@pytest.fixture(params=['monthly', 'annually'])
@pytest.mark.django_db
def complete_current_sa(mocker, request):
    tz = mocker.patch('django.utils.timezone.now', return_value=GENESIS)
    sa = SubscriptionAgreement(
        customer_pk=SENTINEL['customer_pk'],
        customer_type=SENTINEL['customer_type'],
        status='Current',
        current_link_limit=SENTINEL['link_limit'],
        current_rate=SENTINEL['recurring_amount'],
        current_frequency=request.param

    )
    sa.save()
    sr = SubscriptionRequest(
        subscription_agreement=sa,
        amount=SENTINEL['amount'],
        recurring_amount=SENTINEL['recurring_amount'],
        recurring_start_date=GENESIS,
        recurring_frequency=request.param,
        link_limit=SENTINEL['link_limit']
    )
    sr.save()
    assert tz.call_count > 0
    assert sa.current_link_limit == sr.link_limit
    assert sa.current_rate == sr.recurring_amount
    assert sa.current_frequency == sr.recurring_frequency
    return sa


@pytest.fixture()
@pytest.mark.django_db
def complete_canceled_sa(mocker):
    tz = mocker.patch('django.utils.timezone.now', return_value=GENESIS)
    sa = SubscriptionAgreement(
        customer_pk=SENTINEL['customer_pk'],
        customer_type=SENTINEL['customer_type'],
        status='Canceled',
        current_link_limit=SENTINEL['link_limit'],
        current_rate=SENTINEL['recurring_amount'],
        current_frequency=SENTINEL['recurring_frequency'],
        # None in fixture to force type errors if not subsequently set.
        paid_through=None
    )
    sa.save()
    sr = SubscriptionRequest(
        subscription_agreement=sa,
        amount=SENTINEL['amount'],
        recurring_amount=SENTINEL['recurring_amount'],
        recurring_start_date=GENESIS,
        recurring_frequency=SENTINEL['recurring_frequency'],
        link_limit=SENTINEL['link_limit']
    )
    sr.save()
    assert tz.call_count > 0
    assert sa.current_link_limit == sr.link_limit
    assert sa.current_rate == sr.recurring_amount
    assert sa.current_frequency == sr.recurring_frequency
    return sa


@pytest.fixture(params=[
        datetime.datetime.now(tz=timezone(settings.TIME_ZONE)) + relativedelta(days=20),
        datetime.datetime.now(tz=timezone(settings.TIME_ZONE)) + relativedelta(hours=2)
    ])
@pytest.mark.django_db
def current_canceled_sa(complete_canceled_sa, request):
    complete_canceled_sa.paid_through = request.param
    complete_canceled_sa.save()
    return complete_canceled_sa


@pytest.fixture(params=[
        datetime.datetime.now(tz=timezone(settings.TIME_ZONE)) + relativedelta(days=-20),
        datetime.datetime.now(tz=timezone(settings.TIME_ZONE)) + relativedelta(hours=-2)
    ])
@pytest.mark.django_db
def expired_canceled_sa(complete_canceled_sa, request):
    complete_canceled_sa.paid_through = request.param
    complete_canceled_sa.save()
    return complete_canceled_sa


@pytest.fixture(params=CS_DECISIONS)
def decision(request):
    return request.param


@pytest.fixture()
@pytest.mark.django_db
def blank_outgoing_transaction(mocker):
    tz = mocker.patch('django.utils.timezone.now', return_value=GENESIS)
    ot = OutgoingTransaction()
    ot.save()
    assert tz.call_count == 1
    return ot


@pytest.fixture()
@pytest.mark.django_db
def barebones_subscription_request(not_standing_sa):
    return SubscriptionRequest(
        subscription_agreement=not_standing_sa,
        recurring_start_date=GENESIS
    )


@pytest.fixture()
@pytest.mark.django_db
def complete_subscription_request(not_standing_sa):
    sr = SubscriptionRequest(
        subscription_agreement=not_standing_sa,
        amount=SENTINEL['amount'],
        recurring_amount=SENTINEL['recurring_amount'],
        recurring_start_date=GENESIS,
        recurring_frequency=SENTINEL['recurring_frequency'],
        link_limit=SENTINEL['link_limit']
    )
    sr.save()
    return sr


@pytest.fixture()
@pytest.mark.django_db
def barebones_change_request(standing_sa):
    return ChangeRequest(
        subscription_agreement=standing_sa,
        recurring_start_date=GENESIS,
        link_limit=SENTINEL['link_limit']
    )


@pytest.fixture()
@pytest.mark.django_db
def barebones_update_request(standing_sa):
    return UpdateRequest(subscription_agreement=standing_sa)


@pytest.fixture()
@pytest.mark.django_db
def barebones_subscription_request_response(barebones_subscription_request):
    return SubscriptionRequestResponse(related_request=barebones_subscription_request)


@pytest.fixture()
@pytest.mark.django_db
def barebones_change_request_response(barebones_change_request):
    return ChangeRequestResponse(related_request=barebones_change_request)


@pytest.fixture()
@pytest.mark.django_db
def barebones_update_request_response(barebones_update_request):
    return UpdateRequestResponse(related_request=barebones_update_request)


@pytest.fixture
def spoof_django_post_object():
    return QueryDict('a=1,b=2,c=3')


#
# TESTS
#

# Helpers

def test_generate_reference_number_valid(mocker):
    available = mocker.patch('perma_payments.models.is_ref_number_available', autospec=True, return_value=True)

    rn = generate_reference_number()
    available.assert_called_once_with(rn)
    prefix, first, second = rn.split('-')
    assert prefix == REFERENCE_NUMBER_PREFIX
    for char in first + second:
        assert char in RN_SET


def test_generate_reference_number_fails_after_100_tries(mocker):
    available = mocker.patch('perma_payments.models.is_ref_number_available', autospec=True, return_value=False)
    with pytest.raises(Exception) as excinfo:
        generate_reference_number()
    assert "No valid reference_number found" in str(excinfo)
    assert available.call_count == 100


# All Models

def test_model_str_methods(mocker):
    # Patch is_ref_number_available, called in initializing SubscriptionRequests,
    # so that DB access isn't required. Not optimal; is there a better way to test this?
    mocker.patch('perma_payments.models.is_ref_number_available', return_value=True)
    for model in apps.get_app_config('perma_payments').get_models():
        assert 'object' not in str(model())


# SubscriptionAgreement

def test_sa_required_fields():
    absent_required_fields_raise_validation_error(
        SubscriptionAgreement(), [
            'customer_pk',
            'customer_type',
            'status'
        ]
    )

@pytest.mark.django_db
def test_sa_autopopulated_fields(standing_sa):
    autopopulated_fields_present(
        standing_sa, [
            'created_date',
            'updated_date',
            'cancellation_requested'
        ]
    )

@pytest.mark.django_db
def test_sa_customer_standard_standing_subscription_true(standing_sa):
    assert SubscriptionAgreement.customer_standing_subscription(standing_sa.customer_pk, standing_sa.customer_type)


@pytest.mark.django_db
def test_sa_customer_current_cancelled_subscription_true(current_canceled_sa):
    assert SubscriptionAgreement.customer_standing_subscription(current_canceled_sa.customer_pk, current_canceled_sa.customer_type)


@pytest.mark.django_db
def test_sa_customer_expired_cancelled_subscription_not_standing(expired_canceled_sa):
    assert not SubscriptionAgreement.customer_standing_subscription(expired_canceled_sa.customer_pk, expired_canceled_sa.customer_type)


@pytest.mark.django_db
def test_sa_customer_subscription_not_standing(not_standing_sa):
    assert not SubscriptionAgreement.customer_standing_subscription(not_standing_sa.customer_pk, not_standing_sa.customer_type)


@pytest.mark.django_db
def test_sa_customer_subscription_no_subscription():
    assert SubscriptionAgreement.objects.count() == 0
    assert not SubscriptionAgreement.customer_standing_subscription(SENTINEL['customer_pk'], SENTINEL['customer_type'])


@pytest.mark.django_db
def test_sa_customer_subscription_with_incorrect_type(multiple_standing_sa):
    assert not SubscriptionAgreement.customer_standing_subscription(multiple_standing_sa.customer_pk, 'arbitrary non-matching string')


@pytest.mark.django_db
def test_sa_customer_subscription_multiple_with_raise(settings, multiple_standing_sa):
    settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND = True
    with pytest.raises(SubscriptionAgreement.MultipleObjectsReturned):
        SubscriptionAgreement.customer_standing_subscription(multiple_standing_sa.customer_pk, multiple_standing_sa.customer_type)


@pytest.mark.django_db
def test_sa_customer_subscription_multiple_without_raise(settings, multiple_standing_sa):
    settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND = False
    assert SubscriptionAgreement.customer_standing_subscription(multiple_standing_sa.customer_pk, multiple_standing_sa.customer_type) == multiple_standing_sa


@pytest.mark.django_db
def test_sa_can_be_altered_true(standing_sa):
    assert standing_sa.can_be_altered()


@pytest.mark.django_db
def test_sa_can_be_altered_false_if_cancellation_requested(standing_sa_cancellation_requested):
    assert not standing_sa_cancellation_requested.can_be_altered()


@pytest.mark.django_db
def test_sa_can_be_altered_false_if_not_standing(not_standing_sa):
    assert not not_standing_sa.can_be_altered()


@pytest.mark.django_db
def test_sa_update_after_cs_decision(complete_pending_sa, decision, mocker):
    log = mocker.patch('perma_payments.models.logger.log', autospec=True)
    assert not complete_pending_sa.current_link_limit
    assert not complete_pending_sa.current_rate
    assert not complete_pending_sa.current_frequency
    complete_pending_sa.update_after_cs_decision(decision, {})
    assert complete_pending_sa.status != 'Pending'
    if decision in ["ACCEPT", "REVIEW"]:
        assert complete_pending_sa.current_link_limit == complete_pending_sa.subscription_request.link_limit
        assert complete_pending_sa.current_rate == complete_pending_sa.subscription_request.recurring_amount
        assert complete_pending_sa.current_frequency == complete_pending_sa.subscription_request.recurring_frequency
    else:
        assert not complete_pending_sa.current_link_limit
        assert not complete_pending_sa.current_rate
        assert not complete_pending_sa.current_frequency
    assert log.call_count == 1


@pytest.mark.django_db
def test_sa_calculate_paid_through_date_annual(complete_current_sa):
    # lame test just to pass through some of the code
    assert complete_current_sa.calculate_paid_through_date_from_reported_status('Current').tzinfo


# OutgoingTransaction

def test_outgoing_required_fields():
    # None yet!
    absent_required_fields_raise_validation_error(
        OutgoingTransaction(), [
        ]
    )

@pytest.mark.django_db
def test_outgoing_autopopulated_fields(blank_outgoing_transaction):
    autopopulated_fields_present(
        blank_outgoing_transaction, [
            'transaction_uuid',
            'request_datetime'
        ]
    )

@pytest.mark.django_db
def test_outgoing_get_formatted_datetime(blank_outgoing_transaction):
    assert blank_outgoing_transaction.get_formatted_datetime() == '1970-01-01T00:00:00Z'


# SubscriptionRequest

def test_sr_inherits_from_outgiong_transaction():
    assert issubclass(SubscriptionRequest, OutgoingTransaction)


def test_sr_required_fields(mocker):
    # Mocked to avoid hitting DB
    mocker.patch('perma_payments.models.is_ref_number_available', return_value=True)
    absent_required_fields_raise_validation_error(
        SubscriptionRequest(), [
            'subscription_agreement',
            'amount',
            'recurring_amount',
            'recurring_start_date',
            'recurring_frequency',
            'link_limit'
        ]
    )


def test_sr_autopopulated_fields(mocker):
    # Mocked to avoid hitting DB
    mocker.patch('perma_payments.models.is_ref_number_available', return_value=True)
    autopopulated_fields_present(
        SubscriptionRequest(), [
            'currency',
            'locale',
            'payment_method',
            'transaction_type'
        ]
    )


@pytest.mark.django_db
def test_sr_customer_retrived(barebones_subscription_request):
    assert barebones_subscription_request.customer_pk == SENTINEL['customer_pk']
    assert barebones_subscription_request.customer_type == SENTINEL['customer_type']


@pytest.mark.django_db
def test_sr_get_formatted_start_date(barebones_subscription_request):
    assert barebones_subscription_request.get_formatted_start_date() == '19700101'


# ChangeRequest

def test_cr_inherits_from_outgiong_transaction():
    assert issubclass(SubscriptionRequest, OutgoingTransaction)


def test_cr_required_fields(mocker):
    # Mocked to avoid hitting DB
    mocker.patch('perma_payments.models.is_ref_number_available', return_value=True)
    absent_required_fields_raise_validation_error(
        ChangeRequest(), [
            'subscription_agreement',
            'amount',
            'recurring_amount',
            'recurring_start_date',
            'recurring_frequency',
            'link_limit'
        ]
    )


def test_cr_autopopulated_fields(mocker):
    # Mocked to avoid hitting DB
    mocker.patch('perma_payments.models.is_ref_number_available', return_value=True)
    autopopulated_fields_present(
        ChangeRequest(), [
            'currency',
            'locale',
            'payment_method',
            'transaction_type'
        ]
    )


@pytest.mark.django_db
def test_cr_customer_retrived(barebones_change_request):
    assert barebones_change_request.customer_pk == SENTINEL['customer_pk']
    assert barebones_change_request.customer_type == SENTINEL['customer_type']


@pytest.mark.django_db
def test_cr_get_formatted_start_date(barebones_change_request):
    assert barebones_change_request.get_formatted_start_date() == '19700101'


# UpdateRequest

def test_update_inherits_from_outgiong_transaction():
    assert issubclass(UpdateRequest, OutgoingTransaction)


def test_update_required_fields():
    absent_required_fields_raise_validation_error(
        UpdateRequest(), [
            'subscription_agreement'
        ]
    )


def test_update_autopopulated_fields():
    autopopulated_fields_present(
        UpdateRequest(), [
            'transaction_type'
        ]
    )

@pytest.mark.django_db
def test_update_customer_retrived(barebones_update_request):
    assert barebones_update_request.customer_pk == SENTINEL['customer_pk']


# Response

def test_response_required_fields():
    absent_required_fields_raise_validation_error(
        Response(), [
            'full_response',
            'encryption_key_id'
        ]
    )


# None yet!
# def test_response_autopopulated_fields():
#     pass


def test_response_related_request_present_but_not_implemented():
    with pytest.raises(NotImplementedError):
        Response().related_request


def test_response_sa_present_but_not_implemented():
    with pytest.raises(NotImplementedError):
        Response().subscription_agreement


def test_response_customer_pk_present_but_not_implemented():
    with pytest.raises(NotImplementedError):
        Response().customer_pk

def test_response_customer_type_present_but_not_implemented():
    with pytest.raises(NotImplementedError):
        Response().customer_type


@pytest.mark.django_db
def test_response_save_new_with_encrypted_full_response_sr(mocker, complete_subscription_request, spoof_django_post_object):
    # mocks
    stringified = mocker.patch('perma_payments.models.stringify_data', return_value=mocker.sentinel.stringified)
    encrypted = mocker.patch('perma_payments.models.encrypt_for_storage', return_value=b'someencryptedbytes')

    # call
    fields = {
        'related_request': complete_subscription_request,
        'decision': random.choice([choice[0] for choice in Response._meta.get_field('decision').choices]),
        'reason_code': SENTINEL['reason_code'],
        'message': SENTINEL['message'],
        'payment_token': SENTINEL['payment_token'],
    }
    Response.save_new_with_encrypted_full_response(SubscriptionRequestResponse, spoof_django_post_object, fields)
    response = complete_subscription_request.subscription_request_response

    # save worked
    assert isinstance(response, SubscriptionRequestResponse)
    for key, value in fields.items():
        assert getattr(response, key) == value
    assert response.full_response == b'someencryptedbytes'

    # mocks called as expected
    stringified.assert_called_once_with(spoof_django_post_object)
    encrypted.assert_called_once_with(mocker.sentinel.stringified)


@pytest.mark.django_db
def test_response_save_new_with_encrypted_full_response_ur(mocker, barebones_update_request, spoof_django_post_object):
    # mocks
    stringified = mocker.patch('perma_payments.models.stringify_data', return_value=mocker.sentinel.stringified)
    encrypted = mocker.patch('perma_payments.models.encrypt_for_storage', return_value=b'someencryptedbytes')

    # call
    barebones_update_request.save()
    fields = {
        'related_request': barebones_update_request,
        'decision': random.choice([choice[0] for choice in Response._meta.get_field('decision').choices]),
        'reason_code': SENTINEL['reason_code'],
        'message': SENTINEL['message']
    }
    Response.save_new_with_encrypted_full_response(UpdateRequestResponse, spoof_django_post_object, fields)
    response = barebones_update_request.update_request_response

    # save worked
    assert isinstance(response, UpdateRequestResponse)
    for key, value in fields.items():
        assert getattr(response, key) == value
    assert response.full_response == b'someencryptedbytes'

    # mocks called as expected
    stringified.assert_called_once_with(spoof_django_post_object)
    encrypted.assert_called_once_with(mocker.sentinel.stringified)



# SubscriptionRequestResponse

def test_srr_inherits_from_outgiong_transaction():
    assert issubclass(SubscriptionRequestResponse, Response)


def test_srr_required_fields():
    absent_required_fields_raise_validation_error(
        SubscriptionRequestResponse(), [
            'related_request',
            'full_response',
            'encryption_key_id'
        ]
    )


# None yet!
# def test_srr_autopopulated_fields():
#     pass


@pytest.mark.django_db
def test_srr_payment_token_field_present(barebones_subscription_request_response, not_standing_sa):
    assert hasattr(barebones_subscription_request_response, 'payment_token')


@pytest.mark.django_db
def test_srr_sa_retrived(barebones_subscription_request_response, not_standing_sa):
    assert barebones_subscription_request_response.subscription_agreement == not_standing_sa


@pytest.mark.django_db
def test_srr_customer_retrived(barebones_subscription_request_response):
    assert barebones_subscription_request_response.customer_pk == SENTINEL['customer_pk']
    assert barebones_subscription_request_response.customer_type == SENTINEL['customer_type']


# ChangeRequestResponse

def test_crr_inherits_from_outgoing_transaction():
    assert issubclass(ChangeRequestResponse, Response)


def test_crr_required_fields():
    absent_required_fields_raise_validation_error(
        ChangeRequestResponse(), [
            'related_request',
            'full_response',
            'encryption_key_id'
        ]
    )


# None yet!
# def test_crr_autopopulated_fields():
#     pass


@pytest.mark.django_db
def test_crr_sa_retrived(barebones_change_request_response, standing_sa):
    assert barebones_change_request_response.subscription_agreement == standing_sa


@pytest.mark.django_db
def test_crr_customer_retrived(barebones_change_request_response):
    assert barebones_change_request_response.customer_pk == SENTINEL['customer_pk']
    assert barebones_change_request_response.customer_type == SENTINEL['customer_type']


# UpdateRequestResponse

def test_urr_inherits_from_outgiong_transaction():
    assert issubclass(UpdateRequestResponse, Response)


def test_urr_required_fields():
    absent_required_fields_raise_validation_error(
        UpdateRequestResponse(), [
            'related_request',
            'full_response',
            'encryption_key_id'
        ]
    )


# None yet!
# def test_urr_autopopulated_fields():
#     pass


@pytest.mark.django_db
def test_urr_sa_retrived(barebones_update_request_response, standing_sa):
    assert barebones_update_request_response.subscription_agreement == standing_sa


@pytest.mark.django_db
def test_urr_customer_retrived(barebones_update_request_response):
    assert barebones_update_request_response.customer_pk == SENTINEL['customer_pk']
    assert barebones_update_request_response.customer_type == SENTINEL['customer_type']
