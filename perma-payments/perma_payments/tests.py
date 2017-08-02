# from django.test import TestCase
from .security import data_to_string, sign_data


def test_data_to_string_sorted():
    """
        Sorts keys alphabetically, joins in expected format.
    """
    data = {
        "foo": "baz",
        "bar": "bamph",
        "signed_field_names": "bar,foo,signed_field_names"
    }
    data_to_sign = data_to_string(data)
    assert data_to_sign == "bar=bamph,foo=baz,signed_field_names=bar,foo,signed_field_names"


def test_data_to_string_not_sorted():
    """
        Iterates in order, joins in expected format.
    """
    data = {
        "foo": "baz",
        "bar": "bamph",
        "signed_field_names": "foo,bar,signed_field_names"
    }
    data_to_sign = data_to_string(data, sort=False)
    assert data_to_sign == "foo=baz,bar=bamph,signed_field_names=foo,bar,signed_field_names"


def test_sign_data():
    """
        Checks using keys in settings_testing.py
    """
    data_string = "bar=bamph,foo=baz,signed_field_names=bar,foo,signed_field_names"
    assert sign_data(data_string) == b"wmEE0YLoDwXHf6kRe1e8AV9OcaFGNI+2qRQ8t9gS1Fk="
