from ast import literal_eval
from datetime import datetime, timezone
import urllib

from django.core.exceptions import ValidationError
from django.http import QueryDict

from faker import Faker
import pytest

from perma_payments.constants import CS_DECISIONS
from perma_payments.models import SubscriptionRequest


fake = Faker()

GENESIS = datetime.fromtimestamp(0).replace(tzinfo=timezone.utc)

SENTINEL = {
    'datetime': fake.future_date(tzinfo=timezone.utc),
    'registrar_id': fake.random_int(),
    'recurring_frequency': fake.random_element(elements=[status[0] for status in SubscriptionRequest._meta.get_field('recurring_frequency').choices]),
    'amount': fake.pydecimal(left_digits=6, right_digits=2, positive=True),
    'recurring_amount': fake.pydecimal(left_digits=6, right_digits=2, positive=True),
    'bytes': b'sentinel ascii bytes',
    'req_transaction_uuid': fake.uuid4(),
    'decision': fake.random_element(elements=CS_DECISIONS.keys()),
    'reason_code': str(fake.random_int()),
    'message': fake.sentence(nb_words=7),
    'payment_token': fake.password(length=26),
    'invalid_payment_token': fake.password(length=16),
}


class SentinelException(Exception):
    pass


def dict_to_querydict(d):
    return QueryDict(urllib.parse.urlencode(d))


# Models

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


# Views

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

