# from django.test import TestCase
from .views import data_to_string, sign_data

def test_data_to_string():
    """
        Sorts keys alphabetcially, joins in expected format.
    """
    data = {
      "foo": "baz",
      "bar": "bamph",
      "signed_field_names": "bar,foo,signed_field_names"
    }
    data_to_sign = data_to_string(data)
    assert data_to_sign == "bar=bamph,foo=baz,signed_field_names=bar,foo,signed_field_names"

def test_sign_data():
    """
        Checks using keys in settings_test.py
    """
    data_string = "bar=bamph,foo=baz,signed_field_names=bar,foo,signed_field_names"
    assert sign_data(data_string) == b"wmEE0YLoDwXHf6kRe1e8AV9OcaFGNI+2qRQ8t9gS1Fk="
