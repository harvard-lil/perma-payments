from ast import literal_eval
from datetime import datetime, timezone
import decimal
from random import randint, choice

from django.apps import apps
from django.core.exceptions import ValidationError
from django.http import QueryDict

from hypothesis import given
from hypothesis.strategies import characters, text, integers, booleans, datetimes, decimals, lists, tuples, sets, just
import pytest

from perma_payments.models import *

#
# UTILS
#

genesis = datetime.fromtimestamp(0).replace(tzinfo=timezone.utc)

# If we could combine hypothesis with pytest fixtures, these would be
# straight up strategies passed to fixtures/tests instead

registrar_id = randint(1, 1000)
reason_code = randint(1, 1000)
recurring_frequency = random.choice([status[0] for status in SubscriptionRequest._meta.get_field('recurring_frequency').choices])
amount = decimals(places=2, min_value=decimal.Decimal(0.00), allow_nan=False, allow_infinity=False).example()
recurring_amount = decimals(places=2, min_value=decimal.Decimal(0.00), allow_nan=False, allow_infinity=False).example()
message = text(alphabet=characters(min_codepoint=1, blacklist_categories=('Cc', 'Cs'))).example()
payment_token = text(alphabet="0123456789", min_size=26, max_size=26).example()
post = QueryDict('a=1,b=2,c=3')

def absent_required_fields_raise_validation_error(o, fields):
    # If it doesn't work, you might need to add custom validation to the model.
    # For instance, binary fields aren't cleaned by default.
    if fields:
        with pytest.raises(ValidationError) as excinfo:
            o.full_clean()
        error_dict = literal_eval(str(excinfo).split(':', 3)[3].strip())
        assert sorted(fields) == sorted(list(error_dict.keys()))
    else:
        # If no required fields, the following should not raise ValidationError
        o.full_clean()


def autopopulated_fields_present(o, fields):
    """
    Pass in any model instance. If you are testing auto-populated date fields,
    the instance must have been saved, and you must have db access, but otherwise,
    mere instantiation is sufficient. Doesn't work for fields with default=None or default='',
    but this is the most generalized test I can currently dream up.
    """
    for field in fields:
        value = getattr(o, field)
        assert value is not None and value is not ''


#
# FIXTURES
#


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def standing_sa(request):
    sa = SubscriptionAgreement(
        registrar=registrar_id,
        status=request.param
    )
    sa.save()
    return sa


@pytest.fixture(params=[status[0] for status in SubscriptionAgreement._meta.get_field('status').choices if status[0] not in STANDING_STATUSES])
@pytest.mark.django_db
def not_standing_sa(request):
    sa = SubscriptionAgreement(
        registrar=registrar_id,
        status=request.param
    )
    sa.save()
    return sa


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def multiple_standing_sa(request):
    sa1 = SubscriptionAgreement(
        registrar=registrar_id,
        status=request.param
    )
    sa1.save()
    sa2 = SubscriptionAgreement(
        registrar=registrar_id,
        status=request.param
    )
    sa2.save()
    return sa1


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def standing_sa_cancellation_requested(request):
    sa = SubscriptionAgreement(
        registrar=registrar_id,
        status=request.param,
        cancellation_requested=True
    )
    sa.save()
    return sa


@pytest.fixture()
@pytest.mark.django_db
def blank_outgoing_transaction(mocker):
    tz = mocker.patch('django.utils.timezone.now', return_value=genesis)
    ot = OutgoingTransaction()
    ot.save()
    tz.assert_called_once()
    return ot


@pytest.fixture()
@pytest.mark.django_db
def barebones_subscription_request(not_standing_sa):
    return SubscriptionRequest(
        subscription_agreement=not_standing_sa,
        recurring_start_date=genesis
    )


@pytest.fixture()
@pytest.mark.django_db
def complete_subscription_request(not_standing_sa):
    sr = SubscriptionRequest(
        subscription_agreement=not_standing_sa,
        amount=amount,
        recurring_amount=recurring_amount,
        recurring_start_date=genesis,
        recurring_frequency=recurring_frequency
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


#
# TESTS
#

# Helpers

def test_generate_reference_number_valid(mocker):
    formatted = mocker.patch('perma_payments.models.get_formatted_reference_number', autospec=True, return_value=mocker.sentinel.formatted)
    mocker.patch('perma_payments.models.is_ref_number_available', autospec=True, return_value=True)

    generate_reference_number()
    formatted.assert_called_once()
    for c in formatted.call_args[0][0]:
        assert c in RN_SET
    assert REFERENCE_NUMBER_PREFIX == formatted.call_args[0][1]


def test_generate_reference_number_fails_after_100_tries(mocker):
    mocker.patch('perma_payments.models.get_formatted_reference_number', autospec=True)
    available = mocker.patch('perma_payments.models.is_ref_number_available', autospec=True, return_value=False)
    with pytest.raises(Exception) as excinfo:
        generate_reference_number()
    assert "No valid reference_number found" in str(excinfo)
    assert available.call_count == 100


non_characters = just('-') | integers() | booleans() | datetimes() | decimals(allow_nan=False, allow_infinity=False)
@given(non_characters | tuples(non_characters | text(min_size=2), non_characters | text(min_size=2), non_characters | text(min_size=2)) | lists(elements=non_characters | text(min_size=2)) | sets(elements=non_characters | text(min_size=2)))
def test_get_formatted_reference_number_invalid_rn(rn):
    with pytest.raises(TypeError) as excinfo:
        get_formatted_reference_number(rn, 'notempty')
    assert "sequence of non-hyphen characters" in str(excinfo)


@given(just('-') | non_characters)
def test_get_formatted_reference_number_invalid_prefix(prefix):
    with pytest.raises(TypeError) as excinfo:
        get_formatted_reference_number('notempty', prefix)
    assert "string with no hyphens." in str(excinfo)


no_hyphen_string = text(min_size=1, alphabet=characters(min_codepoint=1, blacklist_categories=('Cc', 'Cs'))).filter(lambda s: '-' not in s)
no_hyphen_char = text(min_size=1, max_size=1, alphabet=characters(min_codepoint=1, blacklist_categories=('Cc', 'Cs'))).filter(lambda s: '-' not in s)
no_hyphen_sequences = no_hyphen_string | tuples(no_hyphen_char, no_hyphen_char, no_hyphen_char) | lists(elements=no_hyphen_char, min_size=1)
@given(no_hyphen_sequences, no_hyphen_string)
def test_get_formatted_reference_number_hyphenated(rn, prefix):
    formatted = get_formatted_reference_number(rn, prefix)
    chars = len(rn)
    if chars % 4 == 0:
        assert formatted.count('-') == chars // 4
    else:
        assert formatted.count('-') == ((chars + 4) // 4)
    assert prefix in formatted
    for char in rn:
        assert char in formatted


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
    assert barebones_subscription_request.registrar == registrar_id


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
    assert barebones_update_request.registrar == registrar_id


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
def test_response_save_new_w_encryped_full_response_sr(mocker, complete_subscription_request):
    # mocks
    stringified = mocker.patch('perma_payments.models.stringify_request_post_for_encryption', return_value=mocker.sentinel.stringified)
    nonce = mocker.patch('perma_payments.models.nonce_from_pk', return_value=mocker.sentinel.nonce)
    encrypted = mocker.patch('perma_payments.models.encrypt_for_storage', return_value=b'someencryptedbytes')

    # call
    fields = {
        'related_request': complete_subscription_request,
        'decision': random.choice([choice[0] for choice in Response._meta.get_field('decision').choices]),
        'reason_code': reason_code,
        'message': message,
        'payment_token': payment_token,
    }
    Response.save_new_w_encryped_full_response(SubscriptionRequestResponse, post, fields)
    response = complete_subscription_request.subscription_request_response

    # save worked
    assert isinstance(response, SubscriptionRequestResponse)
    for key, value in fields.items():
        assert getattr(response, key) == value
    assert response.full_response == b'someencryptedbytes'

    # mocks called as expected
    stringified.assert_called_once_with(post)
    nonce.assert_called_once_with(complete_subscription_request)
    encrypted.assert_called_once_with(mocker.sentinel.stringified, mocker.sentinel.nonce)


@pytest.mark.django_db
def test_response_save_new_w_encryped_full_response_ur(mocker, barebones_update_request):
    # mocks
    stringified = mocker.patch('perma_payments.models.stringify_request_post_for_encryption', return_value=mocker.sentinel.stringified)
    nonce = mocker.patch('perma_payments.models.nonce_from_pk', return_value=mocker.sentinel.nonce)
    encrypted = mocker.patch('perma_payments.models.encrypt_for_storage', return_value=b'someencryptedbytes')

    # call
    barebones_update_request.save()
    fields = {
        'related_request': barebones_update_request,
        'decision': random.choice([choice[0] for choice in Response._meta.get_field('decision').choices]),
        'reason_code': reason_code,
        'message': message
    }
    Response.save_new_w_encryped_full_response(UpdateRequestResponse, post, fields)
    response = barebones_update_request.update_request_response

    # save worked
    assert isinstance(response, UpdateRequestResponse)
    for key, value in fields.items():
        assert getattr(response, key) == value
    assert response.full_response == b'someencryptedbytes'

    # mocks called as expected
    stringified.assert_called_once_with(post)
    nonce.assert_called_once_with(barebones_update_request)
    encrypted.assert_called_once_with(mocker.sentinel.stringified, mocker.sentinel.nonce)



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
    assert barebones_subscription_request_response.registrar == registrar_id


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
    assert barebones_update_request_response.registrar == registrar_id
