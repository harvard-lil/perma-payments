"""
Tests for the payment provider abstraction layer.

These tests cover:
- Provider base classes and interfaces
- Provider router functionality
- Individual provider implementations with mocked external services
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from decimal import Decimal

from django.conf import settings
from django.test import RequestFactory

from perma_payments.models import SubscriptionAgreement, PAYMENT_PROVIDER_CHOICES
from perma_payments.providers.base import (
    PaymentProvider,
    CheckoutContext,
    CallbackResult,
    NoProviderAvailable,
    ProviderConfigurationError,
)
from perma_payments.providers.router import (
    get_provider,
    get_customer_provider,
    get_checkout_provider,
    clear_provider_cache,
)
from perma_payments.providers.cybersource_legacy import CybersourceLegacyProvider
from perma_payments.providers.stripe import StripeProvider

from .factories import SubscriptionAgreementFactory, SubscriptionRequestFactory


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear provider cache before each test."""
    clear_provider_cache()
    yield
    clear_provider_cache()


@pytest.fixture
def legacy_provider_config():
    """Configuration for CyberSource legacy provider with test credentials."""
    return {
        'class': 'perma_payments.providers.cybersource_legacy.CybersourceLegacyProvider',
        'mode': 'test',
        'access_key': 'test_access_key',
        'profile_id': 'test_profile_id',
        'secret_key': 'test_secret_key',
    }


@pytest.fixture
def stripe_provider_config():
    """Configuration for Stripe provider with test credentials."""
    return {
        'class': 'perma_payments.providers.stripe.StripeProvider',
        'secret_key': 'sk_test_xxx',
        'publishable_key': 'pk_test_xxx',
        'webhook_secret': 'whsec_xxx',
    }


@pytest.fixture
def rest_provider_config():
    """Configuration for CyberSource REST provider with test credentials."""
    return {
        'class': 'perma_payments.providers.cybersource_rest.CybersourceRestProvider',
        'mode': 'test',
        'merchant_id': 'test_merchant_id',
        'key_id': 'test_key_id',
        'shared_secret': 'test_shared_secret',
    }


# ============================================================================
# Base Provider Tests
# ============================================================================

class TestCheckoutContext:
    """Tests for CheckoutContext dataclass."""
    
    def test_checkout_context_creation(self):
        """Test basic CheckoutContext creation with required fields."""
        context = CheckoutContext(
            template='redirect.html',
            post_url='https://example.com/pay',
            fields_to_post={'key': 'value'},
        )
        assert context.template == 'redirect.html'
        assert context.post_url == 'https://example.com/pay'
        assert context.fields_to_post == {'key': 'value'}
        assert context.client_config == {}  # default
        assert context.extra_context == {}  # default
    
    def test_checkout_context_with_client_config(self):
        """Test CheckoutContext with client-side configuration."""
        context = CheckoutContext(
            template='stripe_checkout.html',
            client_config={'session_id': 'sess_xxx'},
        )
        assert context.template == 'stripe_checkout.html'
        assert context.post_url is None
        assert context.client_config == {'session_id': 'sess_xxx'}
    
    def test_checkout_context_with_extra_context(self):
        """Test CheckoutContext with extra template context."""
        context = CheckoutContext(
            template='flex_microform.html',
            client_config={'capture_context': 'jwt_xxx'},
            extra_context={'custom_field': 'value'},
        )
        assert context.extra_context == {'custom_field': 'value'}


class TestCallbackResult:
    """Tests for CallbackResult dataclass."""
    
    def test_callback_result_success(self):
        """Test successful callback result."""
        result = CallbackResult(
            success=True,
            decision='ACCEPT',
            reason_code='100',
            message='Transaction successful',
            provider_data={'payment_token': 'tok_xxx'},
            raw_response={'id': 'txn_123'},
        )
        assert result.success is True
        assert result.decision == 'ACCEPT'
        assert result.reason_code == '100'
        assert result.provider_data == {'payment_token': 'tok_xxx'}
    
    def test_callback_result_failure(self):
        """Test failed callback result."""
        result = CallbackResult(
            success=False,
            decision='DECLINE',
            reason_code='202',
            message='Card declined',
            provider_data={},
            raw_response={'error': 'declined'},
        )
        assert result.success is False
        assert result.decision == 'DECLINE'
        assert result.reason_code == '202'
    
    def test_callback_result_error(self):
        """Test error callback result."""
        result = CallbackResult(
            success=False,
            decision='ERROR',
            reason_code='PROCESSING_ERROR',
            message='System error',
            provider_data={},
            raw_response={'error': 'system_error'},
        )
        assert result.success is False
        assert result.decision == 'ERROR'


# ============================================================================
# Provider Router Tests
# ============================================================================

class TestProviderRouter:
    """Tests for provider router functions."""
    
    def test_get_provider_loads_class(self, settings, legacy_provider_config):
        """Test that get_provider correctly loads and instantiates provider class."""
        settings.PAYMENT_PROVIDERS = {'cybersource_legacy': legacy_provider_config}
        
        provider = get_provider('cybersource_legacy')
        
        assert isinstance(provider, CybersourceLegacyProvider)
        assert provider.name == 'cybersource_legacy'
    
    def test_get_provider_caches_instance(self, settings, legacy_provider_config):
        """Test that provider instances are cached for reuse."""
        settings.PAYMENT_PROVIDERS = {'cybersource_legacy': legacy_provider_config}
        
        provider1 = get_provider('cybersource_legacy')
        provider2 = get_provider('cybersource_legacy')
        
        assert provider1 is provider2
    
    def test_get_provider_raises_for_unknown(self, settings):
        """Test that get_provider raises error for unconfigured provider."""
        settings.PAYMENT_PROVIDERS = {}
        
        with pytest.raises(ProviderConfigurationError) as exc:
            get_provider('unknown_provider')
        
        assert 'not configured' in str(exc.value)
    
    def test_get_provider_raises_for_missing_class(self, settings):
        """Test that get_provider raises error when class key is missing."""
        settings.PAYMENT_PROVIDERS = {'bad_provider': {'mode': 'test'}}
        
        with pytest.raises(ProviderConfigurationError) as exc:
            get_provider('bad_provider')
        
        assert 'missing' in str(exc.value).lower()
    
    def test_get_provider_raises_for_invalid_class(self, settings):
        """Test that get_provider raises error for non-existent class."""
        settings.PAYMENT_PROVIDERS = {
            'bad_provider': {
                'class': 'nonexistent.module.ProviderClass',
            }
        }
        
        with pytest.raises(ProviderConfigurationError) as exc:
            get_provider('bad_provider')
        
        assert 'Could not import' in str(exc.value)
    
    @pytest.mark.django_db
    def test_get_customer_provider_returns_none_for_no_subscription(
        self, settings, legacy_provider_config
    ):
        """Test that get_customer_provider returns None for non-existent customer."""
        settings.PAYMENT_PROVIDERS = {'cybersource_legacy': legacy_provider_config}
        
        provider = get_customer_provider(customer_pk=99999, customer_type='Individual')
        
        assert provider is None
    
    @pytest.mark.django_db
    def test_get_customer_provider_returns_provider_for_existing_subscription(
        self, settings, legacy_provider_config
    ):
        """Test that get_customer_provider returns correct provider for existing subscription."""
        settings.PAYMENT_PROVIDERS = {'cybersource_legacy': legacy_provider_config}
        
        # Create a standing subscription
        SubscriptionAgreementFactory(
            customer_pk=12345,
            customer_type='Individual',
            status='Current',
            payment_provider='cybersource_legacy',
        )
        
        provider = get_customer_provider(customer_pk=12345, customer_type='Individual')
        
        assert provider is not None
        assert provider.name == 'cybersource_legacy'
    
    @pytest.mark.django_db
    def test_get_checkout_provider_uses_existing_subscription(
        self, settings, legacy_provider_config, stripe_provider_config
    ):
        """Test that get_checkout_provider uses existing customer's provider."""
        settings.PAYMENT_PROVIDERS = {
            'cybersource_legacy': legacy_provider_config,
            'stripe': stripe_provider_config,
        }
        settings.CHECKOUT_PROVIDERS = ['stripe']  # Stripe preferred for new
        
        # Create existing subscription with legacy
        SubscriptionAgreementFactory(
            customer_pk=12345,
            customer_type='Registrar',
            status='Current',
            payment_provider='cybersource_legacy',
        )
        
        # Should use legacy even though stripe is preferred for new
        provider = get_checkout_provider(customer_pk=12345, customer_type='Registrar')
        
        assert provider.name == 'cybersource_legacy'
    
    @pytest.mark.django_db
    def test_get_checkout_provider_probes_in_order(
        self, settings, legacy_provider_config, stripe_provider_config
    ):
        """Test that get_checkout_provider probes providers in configured order."""
        settings.PAYMENT_PROVIDERS = {
            'cybersource_legacy': legacy_provider_config,
            'stripe': stripe_provider_config,
        }
        settings.CHECKOUT_PROVIDERS = ['stripe', 'cybersource_legacy']
        
        # No existing subscription, should use first available (stripe)
        provider = get_checkout_provider(customer_pk=99999, customer_type='Individual')
        
        assert provider.name == 'stripe'
    
    @pytest.mark.django_db
    def test_get_checkout_provider_skips_unconfigured_providers(
        self, settings, legacy_provider_config
    ):
        """Test that get_checkout_provider skips providers that can't handle subscriptions."""
        # Stripe without credentials
        settings.PAYMENT_PROVIDERS = {
            'stripe': {'class': 'perma_payments.providers.stripe.StripeProvider'},
            'cybersource_legacy': legacy_provider_config,
        }
        settings.CHECKOUT_PROVIDERS = ['stripe', 'cybersource_legacy']
        
        # Stripe should be skipped (no credentials), should use legacy
        provider = get_checkout_provider(customer_pk=99999, customer_type='Individual')
        
        assert provider.name == 'cybersource_legacy'
    
    @pytest.mark.django_db
    def test_get_checkout_provider_raises_when_no_provider_available(self, settings):
        """Test that get_checkout_provider raises when no provider is available."""
        settings.PAYMENT_PROVIDERS = {}
        settings.CHECKOUT_PROVIDERS = []
        
        with pytest.raises(NoProviderAvailable):
            get_checkout_provider(customer_pk=99999, customer_type='Individual')


# ============================================================================
# CyberSource Legacy Provider Tests
# ============================================================================

class TestCybersourceLegacyProvider:
    """Tests for CybersourceLegacyProvider."""
    
    def test_provider_name(self, legacy_provider_config):
        """Test that provider has correct name."""
        provider = CybersourceLegacyProvider(legacy_provider_config)
        assert provider.name == 'cybersource_legacy'
    
    def test_can_handle_new_subscription_when_configured(self, legacy_provider_config):
        """Test that configured provider can handle new subscriptions."""
        provider = CybersourceLegacyProvider(legacy_provider_config)
        assert provider.can_handle_new_subscription() is True
    
    def test_can_handle_new_subscription_when_not_configured(self):
        """Test that unconfigured provider cannot handle new subscriptions."""
        # Provider with no credentials in config
        provider = CybersourceLegacyProvider({'mode': 'test'})
        assert provider.can_handle_new_subscription() is False
    
    def test_can_handle_new_subscription_partially_configured(self):
        """Test that partially configured provider cannot handle new subscriptions."""
        # Provider with only access_key, missing profile_id and secret_key
        provider = CybersourceLegacyProvider({
            'mode': 'test',
            'access_key': 'key',
            # Missing profile_id and secret_key
        })
        assert provider.can_handle_new_subscription() is False
    
    @pytest.mark.django_db
    def test_probe_customer_returns_true_for_matching_provider(self, legacy_provider_config):
        """Test probe_customer returns True for customer using this provider."""
        provider = CybersourceLegacyProvider(legacy_provider_config)
        
        SubscriptionAgreementFactory(
            customer_pk=123,
            customer_type='Individual',
            status='Current',
            payment_provider='cybersource_legacy',
        )
        
        assert provider.probe_customer(123, 'Individual') is True
    
    @pytest.mark.django_db
    def test_probe_customer_returns_false_for_different_provider(self, legacy_provider_config):
        """Test probe_customer returns False for customer using different provider."""
        provider = CybersourceLegacyProvider(legacy_provider_config)
        
        SubscriptionAgreementFactory(
            customer_pk=123,
            customer_type='Individual',
            status='Current',
            payment_provider='stripe',  # Different provider
        )
        
        assert provider.probe_customer(123, 'Individual') is False
    
    @pytest.mark.django_db
    def test_probe_customer_returns_false_for_no_subscription(self, legacy_provider_config):
        """Test probe_customer returns False for customer with no subscription."""
        provider = CybersourceLegacyProvider(legacy_provider_config)
        
        assert provider.probe_customer(99999, 'Individual') is False
    
    @pytest.mark.django_db
    def test_get_checkout_context_for_subscribe(self, legacy_provider_config, mocker):
        """Test get_checkout_context returns correct context for subscription."""
        provider = CybersourceLegacyProvider(legacy_provider_config)
        
        # Create a subscription request
        sr = SubscriptionRequestFactory()
        
        # Mock prep_for_cybersource
        mock_prep = mocker.patch(
            'perma_payments.providers.cybersource_legacy.prep_for_cybersource',
            return_value={'signed': 'fields'}
        )
        
        context = provider.get_checkout_context(
            request_type='subscribe',
            request_data={},
            outgoing_transaction=sr,
            return_url='https://example.com/',
        )
        
        assert context.template == 'redirect.html'
        assert context.post_url == 'https://testsecureacceptance.cybersource.com/pay'
        assert context.fields_to_post == {'signed': 'fields'}
        mock_prep.assert_called_once()
    
    @pytest.mark.django_db
    def test_get_checkout_context_for_purchase(self, legacy_provider_config, mocker):
        """Test get_checkout_context returns correct context for purchase."""
        from .factories import PurchaseRequestFactory
        
        provider = CybersourceLegacyProvider(legacy_provider_config)
        
        # Create a purchase request
        pr = PurchaseRequestFactory()
        
        # Mock prep_for_cybersource
        mock_prep = mocker.patch(
            'perma_payments.providers.cybersource_legacy.prep_for_cybersource',
            return_value={'signed': 'purchase_fields'}
        )
        
        context = provider.get_checkout_context(
            request_type='purchase',
            request_data={},
            outgoing_transaction=pr,
            return_url='https://example.com/',
        )
        
        assert context.template == 'redirect.html'
        assert context.fields_to_post == {'signed': 'purchase_fields'}
        mock_prep.assert_called_once()
    
    def test_process_callback_success(self, legacy_provider_config, request_factory, mocker):
        """Test process_callback handles successful response."""
        provider = CybersourceLegacyProvider(legacy_provider_config)
        
        # Mock process_cybersource_transmission
        mocker.patch(
            'perma_payments.providers.cybersource_legacy.process_cybersource_transmission',
            return_value={
                'decision': 'ACCEPT',
                'reason_code': '100',
                'message': 'Approved',
                'req_transaction_uuid': 'uuid-123',
                'payment_token': 'tok_xxx',
            }
        )
        
        request = request_factory.post('/', {
            'decision': 'ACCEPT',
            'payment_token': 'tok_xxx',
        })
        
        result = provider.process_callback(request)
        
        assert result.success is True
        assert result.decision == 'ACCEPT'
        assert result.provider_data == {'payment_token': 'tok_xxx'}
    
    def test_process_callback_decline(self, legacy_provider_config, request_factory, mocker):
        """Test process_callback handles decline response."""
        provider = CybersourceLegacyProvider(legacy_provider_config)
        
        mocker.patch(
            'perma_payments.providers.cybersource_legacy.process_cybersource_transmission',
            return_value={
                'decision': 'DECLINE',
                'reason_code': '202',
                'message': 'Card declined',
                'req_transaction_uuid': 'uuid-123',
            }
        )
        
        request = request_factory.post('/', {'decision': 'DECLINE'})
        
        result = provider.process_callback(request)
        
        assert result.success is False
        assert result.decision == 'DECLINE'
        assert result.reason_code == '202'


# ============================================================================
# Stripe Provider Tests
# ============================================================================

class TestStripeProvider:
    """Tests for StripeProvider."""
    
    def test_provider_name(self, stripe_provider_config):
        """Test that provider has correct name."""
        provider = StripeProvider(stripe_provider_config)
        assert provider.name == 'stripe'
    
    def test_can_handle_new_subscription_when_configured(self, stripe_provider_config):
        """Test that configured provider can handle new subscriptions."""
        provider = StripeProvider(stripe_provider_config)
        assert provider.can_handle_new_subscription() is True
    
    def test_can_handle_new_subscription_when_not_configured(self):
        """Test that unconfigured provider cannot handle new subscriptions."""
        provider = StripeProvider({})
        assert provider.can_handle_new_subscription() is False
    
    def test_can_handle_new_subscription_partially_configured(self):
        """Test that partially configured provider cannot handle new subscriptions."""
        provider = StripeProvider({'secret_key': 'sk_test_xxx'})
        # Missing publishable_key
        assert provider.can_handle_new_subscription() is False
    
    @pytest.mark.django_db
    def test_probe_customer_returns_true_for_matching_provider(self, stripe_provider_config):
        """Test probe_customer returns True for customer using Stripe."""
        provider = StripeProvider(stripe_provider_config)
        
        SubscriptionAgreementFactory(
            customer_pk=456,
            customer_type='Registrar',
            status='Current',
            payment_provider='stripe',
        )
        
        assert provider.probe_customer(456, 'Registrar') is True
    
    @pytest.mark.django_db
    def test_probe_customer_returns_false_for_different_provider(self, stripe_provider_config):
        """Test probe_customer returns False for customer using different provider."""
        provider = StripeProvider(stripe_provider_config)
        
        SubscriptionAgreementFactory(
            customer_pk=456,
            customer_type='Registrar',
            status='Current',
            payment_provider='cybersource_legacy',
        )
        
        assert provider.probe_customer(456, 'Registrar') is False
    
    @pytest.mark.django_db
    def test_get_checkout_context_creates_session(self, stripe_provider_config, mocker):
        """Test get_checkout_context creates Stripe Checkout session."""
        provider = StripeProvider(stripe_provider_config)
        
        # Mock the stripe module
        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.id = 'cs_test_xxx'
        mock_session.url = 'https://checkout.stripe.com/xxx'
        mock_stripe.checkout.Session.create.return_value = mock_session
        mocker.patch.object(provider, '_get_stripe', return_value=mock_stripe)
        
        # Create a subscription request
        sr = SubscriptionRequestFactory()
        
        context = provider.get_checkout_context(
            request_type='subscribe',
            request_data={},
            outgoing_transaction=sr,
            return_url='https://example.com/',
        )
        
        assert context.template == 'stripe_checkout.html'
        assert context.client_config['session_id'] == 'cs_test_xxx'
        assert context.client_config['publishable_key'] == 'pk_test_xxx'
        assert context.extra_context['checkout_url'] == 'https://checkout.stripe.com/xxx'
        mock_stripe.checkout.Session.create.assert_called_once()
    
    @pytest.mark.django_db
    def test_get_checkout_context_for_purchase(self, stripe_provider_config, mocker):
        """Test get_checkout_context for one-time purchase."""
        from .factories import PurchaseRequestFactory
        
        provider = StripeProvider(stripe_provider_config)
        
        # Mock the stripe module
        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.id = 'cs_test_purchase'
        mock_session.url = 'https://checkout.stripe.com/purchase'
        mock_stripe.checkout.Session.create.return_value = mock_session
        mocker.patch.object(provider, '_get_stripe', return_value=mock_stripe)
        
        pr = PurchaseRequestFactory()
        
        context = provider.get_checkout_context(
            request_type='purchase',
            request_data={},
            outgoing_transaction=pr,
            return_url='https://example.com/',
        )
        
        assert context.template == 'stripe_checkout.html'
        # Check that mode was 'payment' not 'subscription'
        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        assert call_kwargs['mode'] == 'payment'
    
    def test_process_callback_success(self, stripe_provider_config, request_factory, mocker):
        """Test process_callback handles successful checkout."""
        provider = StripeProvider(stripe_provider_config)
        
        # Mock stripe
        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.payment_status = 'paid'
        mock_session.customer = 'cus_xxx'
        mock_session.id = 'cs_xxx'
        mock_session.subscription = 'sub_xxx'
        mock_session.payment_intent = 'pi_xxx'
        mock_session.to_dict.return_value = {'id': 'cs_xxx'}
        mock_stripe.checkout.Session.retrieve.return_value = mock_session
        mocker.patch.object(provider, '_get_stripe', return_value=mock_stripe)
        
        request = request_factory.get('/', {'session_id': 'cs_xxx'})
        
        result = provider.process_callback(request)
        
        assert result.success is True
        assert result.decision == 'ACCEPT'
        assert result.provider_data['customer_id'] == 'cus_xxx'
        assert result.provider_data['subscription_id'] == 'sub_xxx'
    
    def test_process_callback_missing_session_id(self, stripe_provider_config, request_factory):
        """Test process_callback handles missing session_id."""
        provider = StripeProvider(stripe_provider_config)
        
        request = request_factory.get('/')
        
        result = provider.process_callback(request)
        
        assert result.success is False
        assert result.decision == 'ERROR'
        assert 'session_id' in result.message.lower()
    
    def test_process_callback_payment_not_completed(
        self, stripe_provider_config, request_factory, mocker
    ):
        """Test process_callback handles incomplete payment."""
        provider = StripeProvider(stripe_provider_config)
        
        # Mock session with unpaid status
        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.payment_status = 'unpaid'
        mock_session.to_dict.return_value = {'id': 'cs_xxx'}
        mock_stripe.checkout.Session.retrieve.return_value = mock_session
        mocker.patch.object(provider, '_get_stripe', return_value=mock_stripe)
        
        request = request_factory.get('/', {'session_id': 'cs_xxx'})
        
        result = provider.process_callback(request)
        
        assert result.success is False
        assert result.decision == 'DECLINE'
    
    def test_process_webhook_checkout_completed(self, stripe_provider_config, request_factory, mocker):
        """Test process_webhook handles checkout.session.completed event."""
        provider = StripeProvider(stripe_provider_config)
        
        # Mock stripe
        mock_stripe = MagicMock()
        mock_event = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_xxx',
                    'customer': 'cus_xxx',
                    'subscription': 'sub_xxx',
                }
            }
        }
        mock_stripe.Webhook.construct_event.return_value = mock_event
        mocker.patch.object(provider, '_get_stripe', return_value=mock_stripe)
        
        request = request_factory.post(
            '/',
            data=b'{}',
            content_type='application/json',
        )
        request.META['HTTP_STRIPE_SIGNATURE'] = 'sig_xxx'
        
        result = provider.process_webhook(request)
        
        assert result.success is True
        assert result.decision == 'ACCEPT'
        assert result.provider_data['subscription_id'] == 'sub_xxx'
    
    def test_process_webhook_subscription_deleted(
        self, stripe_provider_config, request_factory, mocker
    ):
        """Test process_webhook handles customer.subscription.deleted event."""
        provider = StripeProvider(stripe_provider_config)
        
        # Mock stripe
        mock_stripe = MagicMock()
        mock_event = {
            'type': 'customer.subscription.deleted',
            'data': {
                'object': {
                    'id': 'sub_xxx',
                    'customer': 'cus_xxx',
                }
            }
        }
        mock_stripe.Webhook.construct_event.return_value = mock_event
        mocker.patch.object(provider, '_get_stripe', return_value=mock_stripe)
        
        request = request_factory.post(
            '/',
            data=b'{}',
            content_type='application/json',
        )
        request.META['HTTP_STRIPE_SIGNATURE'] = 'sig_xxx'
        
        result = provider.process_webhook(request)
        
        assert result.success is True
        assert result.decision == 'CANCEL'
        assert result.reason_code == 'SUBSCRIPTION_DELETED'


# ============================================================================
# Model Tests for Provider Fields
# ============================================================================

class TestSubscriptionAgreementProviderFields:
    """Tests for provider-related fields on SubscriptionAgreement."""
    
    @pytest.mark.django_db
    def test_default_payment_provider(self):
        """Test that default payment provider is cybersource_legacy."""
        sa = SubscriptionAgreementFactory()
        assert sa.payment_provider == 'cybersource_legacy'
    
    @pytest.mark.django_db
    def test_provider_data_default_empty_dict(self):
        """Test that provider_data defaults to empty dict."""
        sa = SubscriptionAgreementFactory()
        assert sa.provider_data == {}
    
    @pytest.mark.django_db
    def test_payment_token_property_for_legacy(self):
        """Test payment_token property returns correct value for legacy provider."""
        sa = SubscriptionAgreementFactory(
            payment_provider='cybersource_legacy',
            provider_data={'payment_token': 'tok_legacy_xxx'},
        )
        assert sa.payment_token == 'tok_legacy_xxx'
    
    @pytest.mark.django_db
    def test_payment_token_property_for_stripe(self):
        """Test payment_token property returns subscription_id for Stripe."""
        sa = SubscriptionAgreementFactory(
            payment_provider='stripe',
            provider_data={'subscription_id': 'sub_xxx'},
        )
        assert sa.payment_token == 'sub_xxx'
    
    @pytest.mark.django_db
    def test_payment_token_property_for_rest(self):
        """Test payment_token property returns subscription_id for REST provider."""
        sa = SubscriptionAgreementFactory(
            payment_provider='cybersource_rest',
            provider_data={'subscription_id': 'rest_sub_xxx'},
        )
        assert sa.payment_token == 'rest_sub_xxx'
    
    @pytest.mark.django_db
    def test_payment_token_property_returns_none_when_missing(self):
        """Test payment_token property returns None when data is missing."""
        sa = SubscriptionAgreementFactory(
            payment_provider='stripe',
            provider_data={},  # No subscription_id
        )
        assert sa.payment_token is None
    
    @pytest.mark.django_db
    def test_payment_provider_choices(self):
        """Test that all provider choices can be saved."""
        for choice in PAYMENT_PROVIDER_CHOICES:
            sa = SubscriptionAgreementFactory(payment_provider=choice)
            assert sa.payment_provider == choice
    
    @pytest.mark.django_db
    def test_provider_data_stores_complex_data(self):
        """Test that provider_data can store complex nested data."""
        complex_data = {
            'customer_id': 'cus_xxx',
            'subscription_id': 'sub_xxx',
            'payment_method_id': 'pm_xxx',
            'metadata': {
                'created': '2024-01-01',
                'plan': 'premium',
            }
        }
        sa = SubscriptionAgreementFactory(
            payment_provider='stripe',
            provider_data=complex_data,
        )
        sa.save()
        sa.refresh_from_db()
        assert sa.provider_data == complex_data


# ============================================================================
# Integration Tests
# ============================================================================

class TestProviderViewIntegration:
    """Integration tests for provider usage in views."""
    
    @pytest.mark.django_db
    def test_subscribe_view_uses_provider(self, client, mocker, settings, legacy_provider_config):
        """Test that subscribe view correctly uses the provider abstraction."""
        settings.PAYMENT_PROVIDERS = {'cybersource_legacy': legacy_provider_config}
        settings.CHECKOUT_PROVIDERS = ['cybersource_legacy']
        
        # Mock the transmission processing
        mocker.patch(
            'perma_payments.views.process_perma_transmission',
            return_value={
                'customer_pk': 12345,
                'customer_type': 'Individual',
                'amount': '10.00',
                'recurring_amount': '10.00',
                'recurring_frequency': 'monthly',
                'recurring_start_date': '2024-02-01',
                'link_limit': '100',
                'link_limit_effective_timestamp': 1704067200,
            }
        )
        
        # Mock prep_for_cybersource
        mocker.patch(
            'perma_payments.providers.cybersource_legacy.prep_for_cybersource',
            return_value={'signed_field': 'value'}
        )
        
        response = client.post('/subscribe/', {'encrypted_data': 'xxx'})
        
        assert response.status_code == 200
        assert 'redirect.html' in [t.name for t in response.templates]
