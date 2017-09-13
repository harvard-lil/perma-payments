# from hypothesis import given
# from hypothesis.strategies import characters, text, integers, booleans, datetimes, dates, decimals, uuids, binary, lists, dictionaries
import pytest

from perma_payments.views import *

#
# Here, we are testing urls.py, views.py, and template rendering
# all in one spot, for simplicity.
#

#
# UTILS
#
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
    return {
        'route': '/subscribe/',
        'template': 'redirect.html'
    }


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

def test_subscribe_post(subscribe):
    pass


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

