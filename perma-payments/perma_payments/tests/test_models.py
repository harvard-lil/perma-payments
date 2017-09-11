
from hypothesis import given
from hypothesis.strategies import text, integers, booleans, datetimes, decimals, lists, tuples, sets, just
import pytest

from perma_payments.models import *

#
# UTILS
#


#
# FIXTURES
#

@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def standing_sa(request):
    sa = SubscriptionAgreement(
       registrar=1,
       status=request.param
    )
    sa.save()
    return sa


@pytest.fixture(params=[status[0] for status in SubscriptionAgreement._meta.get_field('status').choices if status[0] not in STANDING_STATUSES])
@pytest.mark.django_db
def not_standing_sa(request):
    sa = SubscriptionAgreement(
       registrar=1,
       status=request.param
    )
    sa.save()
    return sa


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def multiple_standing_sa(request):
    sa1 = SubscriptionAgreement(
       registrar=1,
       status=request.param
    )
    sa1.save()
    sa2 = SubscriptionAgreement(
       registrar=1,
       status=request.param
    )
    sa2.save()
    return sa1


@pytest.fixture(params=STANDING_STATUSES)
@pytest.mark.django_db
def standing_sa_cancellation_requested(request):
    sa = SubscriptionAgreement(
       registrar=1,
       status=request.param,
       cancellation_requested=True
    )
    sa.save()
    return sa


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


no_hypen_string = text(min_size=1).filter(lambda s: '-' not in s)
no_hypen_char = text(min_size=1, max_size=1).filter(lambda s: '-' not in s)
no_hypen_sequences = no_hypen_string | tuples(no_hypen_char, no_hypen_char, no_hypen_char) | lists(elements=no_hypen_char, min_size=1)
@given(no_hypen_sequences, no_hypen_string)
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


# classes

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

