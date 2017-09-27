from django.apps import apps
from django.http import QueryDict

import pytest

from perma_payments.constants import CS_DECISIONS
from perma_payments.models import *

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
        registrar=SENTINEL['registrar_id'],
        status=request.param
    )
    sa.save()
    return sa


@pytest.fixture(params=[status[0] for status in SubscriptionAgreement._meta.get_field('status').choices if status[0] not in STANDING_STATUSES])
@pytest.mark.django_db
def not_standing_sa(request):
    sa = SubscriptionAgreement(
        registrar=SENTINEL['registrar_id'],
        status=request.param
    )
    sa.save()
    return sa


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def multiple_standing_sa(request):
    sa1 = SubscriptionAgreement(
        registrar=SENTINEL['registrar_id'],
        status=request.param
    )
    sa1.save()
    sa2 = SubscriptionAgreement(
        registrar=SENTINEL['registrar_id'],
        status=request.param
    )
    sa2.save()
    return sa1


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def standing_sa_cancellation_requested(request):
    sa = SubscriptionAgreement(
        registrar=SENTINEL['registrar_id'],
        status=request.param,
        cancellation_requested=True
    )
    sa.save()
    return sa


@pytest.fixture()
@pytest.mark.django_db
def complete_pending_sa():
    sa = SubscriptionAgreement(
        registrar=SENTINEL['registrar_id'],
        status='Pending'
    )
    sa.save()
    sr = SubscriptionRequest(
        subscription_agreement=sa,
        amount=SENTINEL['amount'],
        recurring_amount=SENTINEL['recurring_amount'],
        recurring_start_date=GENESIS,
        recurring_frequency=SENTINEL['recurring_frequency']
    )
    sr.save()
    return sa


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
        recurring_frequency=SENTINEL['recurring_frequency']
    )
    sr.save()
    return sr


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
            'registrar',
            'status'
        ]
    )

@pytest.mark.django_db
def test_sa_autopopulated_fields(standing_sa):
    autopopulated_fields_present(
        standing_sa, [
            'status_updated',
            'cancellation_requested'
        ]
    )

@pytest.mark.django_db
def test_sa_registrar_standing_subscription_true(standing_sa):
    assert SubscriptionAgreement.registrar_standing_subscription(standing_sa.registrar)


@pytest.mark.django_db
def test_sa_registrar_subscription_not_standing(not_standing_sa):
    assert not SubscriptionAgreement.registrar_standing_subscription(not_standing_sa.registrar)


@pytest.mark.django_db
def test_sa_registrar_subscription_no_subscription():
    assert SubscriptionAgreement.objects.count() == 0
    assert not SubscriptionAgreement.registrar_standing_subscription(1)


@pytest.mark.django_db
def test_sa_registrar_subscription_multiple_with_raise(settings, multiple_standing_sa):
    settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND = True
    with pytest.raises(SubscriptionAgreement.MultipleObjectsReturned):
        SubscriptionAgreement.registrar_standing_subscription(multiple_standing_sa.registrar)


@pytest.mark.django_db
def test_sa_registrar_subscription_multiple_without_raise(settings, multiple_standing_sa):
    settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND = False
    assert SubscriptionAgreement.registrar_standing_subscription(multiple_standing_sa.registrar) == multiple_standing_sa


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
def test_sa_update_status_after_cs_decision(complete_pending_sa, decision, mocker):
    log = mocker.patch('perma_payments.models.logger.log', autospec=True)
    complete_pending_sa.update_status_after_cs_decision(decision, {})
    assert complete_pending_sa.status != 'Pending'
    assert log.call_count == 1


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
            'recurring_frequency'
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
def test_sr_registrar_retrived(barebones_subscription_request):
    assert barebones_subscription_request.registrar == SENTINEL['registrar_id']


@pytest.mark.django_db
def test_sr_get_formatted_start_date(barebones_subscription_request):
    assert barebones_subscription_request.get_formatted_start_date() == '19700101'


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
def test_update_registrar_retrived(barebones_update_request):
    assert barebones_update_request.registrar == SENTINEL['registrar_id']


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


def test_response_registrar_present_but_not_implemented():
    with pytest.raises(NotImplementedError):
        Response().registrar


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
def test_srr_registrar_retrived(barebones_subscription_request_response):
    assert barebones_subscription_request_response.registrar == SENTINEL['registrar_id']


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
def test_urr_registrar_retrived(barebones_update_request_response):
    assert barebones_update_request_response.registrar == SENTINEL['registrar_id']
