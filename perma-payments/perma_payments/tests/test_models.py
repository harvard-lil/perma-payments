
from hypothesis import given
from hypothesis.strategies import text, integers, booleans, datetimes, dates, decimals, uuids, binary, lists, dictionaries, tuples, sets, just
import pytest

from perma_payments.models import *

#
# UTILS
#


#
# HELPERS
#


#
# TESTS
#

# Helpers

def test_generate_reference_number_valid(mocker):
    formatted = mocker.patch('perma_payments.models.get_formatted_reference_number', autospec=True, return_value=mocker.sentinel.formatted)
    available = mocker.patch('perma_payments.models.is_ref_number_available', autospec=True, return_value=True)

    rn = generate_reference_number()
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
@given(non_characters | tuples(non_characters | text(), non_characters | text(), non_characters | text()) | lists(elements=non_characters | text()) | sets(elements=non_characters | text()))
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

