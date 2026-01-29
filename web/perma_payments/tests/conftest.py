"""
Pytest configuration and shared fixtures for perma_payments tests.
"""

import pytest
from unittest.mock import Mock, MagicMock

from perma_payments.providers.base import CheckoutContext


@pytest.fixture
def mock_checkout_provider(mocker):
    """
    Fixture that mocks get_checkout_provider to return a mock provider.
    
    The mock provider's get_checkout_context method returns a CheckoutContext
    that uses 'redirect.html' (legacy behavior).
    
    Usage:
        def test_something(client, mock_checkout_provider):
            provider_mock, get_provider_mock = mock_checkout_provider
            # provider_mock is the provider instance
            # get_provider_mock is the patched get_checkout_provider function
    """
    provider_mock = Mock()
    provider_mock.name = 'cybersource_legacy'
    provider_mock.get_checkout_context.return_value = CheckoutContext(
        template='redirect.html',
        post_url='https://testsecureacceptance.cybersource.com/pay',
        fields_to_post={'signed_field': 'value'},
    )
    
    get_provider_mock = mocker.patch(
        'perma_payments.views.get_checkout_provider',
        return_value=provider_mock
    )
    
    # Also mock get_provider for change/update views
    mocker.patch(
        'perma_payments.views.get_provider',
        return_value=provider_mock
    )
    
    return provider_mock, get_provider_mock


@pytest.fixture
def mock_legacy_provider_context():
    """
    Fixture that provides a factory for creating mock CheckoutContext.
    
    This can be used to customize the context returned by the provider.
    
    Usage:
        def test_something(mock_checkout_provider, mock_legacy_provider_context):
            provider_mock, _ = mock_checkout_provider
            provider_mock.get_checkout_context.return_value = mock_legacy_provider_context(
                fields_to_post={'custom': 'fields'}
            )
    """
    def _create_context(fields_to_post=None, post_url=None, template=None):
        return CheckoutContext(
            template=template or 'redirect.html',
            post_url=post_url or 'https://testsecureacceptance.cybersource.com/pay',
            fields_to_post=fields_to_post or {},
        )
    return _create_context


@pytest.fixture
def mock_stripe_provider(mocker):
    """
    Fixture that mocks get_checkout_provider to return a mock Stripe provider.
    
    Usage:
        def test_stripe_checkout(client, mock_stripe_provider):
            provider_mock, get_provider_mock = mock_stripe_provider
    """
    provider_mock = Mock()
    provider_mock.name = 'stripe'
    provider_mock.get_checkout_context.return_value = CheckoutContext(
        template='stripe_checkout.html',
        client_config={'session_id': 'cs_test_xxx', 'publishable_key': 'pk_test_xxx'},
        extra_context={'checkout_url': 'https://checkout.stripe.com/xxx'},
    )
    
    get_provider_mock = mocker.patch(
        'perma_payments.views.get_checkout_provider',
        return_value=provider_mock
    )
    
    return provider_mock, get_provider_mock


@pytest.fixture
def mock_stripe_module(mocker):
    """
    Fixture that mocks the stripe module for testing Stripe provider.
    
    Returns a MagicMock that can be configured with expected responses.
    
    Usage:
        def test_stripe(mock_stripe_module):
            mock_session = MagicMock()
            mock_session.id = 'cs_test_xxx'
            mock_stripe_module.checkout.Session.create.return_value = mock_session
    """
    mock_stripe = MagicMock()
    mocker.patch.dict('sys.modules', {'stripe': mock_stripe})
    return mock_stripe


# Re-export factories for convenience
from .factories import (
    PurchaseRequestFactory,
    PurchaseRequestResponseFactory,
    SubscriptionAgreementFactory,
    SubscriptionRequestFactory,
    SubscriptionRequestResponseFactory,
    ChangeRequestFactory,
    UpdateRequestFactory,
)
