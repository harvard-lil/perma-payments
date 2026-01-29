"""
Provider router for selecting and instantiating payment providers.

This module handles the logic for:
- Getting a provider by name
- Finding the provider for an existing customer
- Selecting a provider for new subscriptions (with fallback probing)
"""

import logging
from typing import Optional

from django.conf import settings
from django.utils.module_loading import import_string

from .base import PaymentProvider, NoProviderAvailable, ProviderConfigurationError

logger = logging.getLogger(__name__)

# Cache for provider instances
_provider_cache: dict[str, PaymentProvider] = {}


def get_provider(name: str) -> PaymentProvider:
    """
    Get a provider instance by name.
    
    Provider instances are cached for reuse.
    
    Args:
        name: Provider name (key in settings.PAYMENT_PROVIDERS)
        
    Returns:
        Configured PaymentProvider instance
        
    Raises:
        ProviderConfigurationError: If the provider is not configured or cannot be loaded
    """
    if name in _provider_cache:
        return _provider_cache[name]
    
    provider_configs = getattr(settings, 'PAYMENT_PROVIDERS', {})
    
    if name not in provider_configs:
        raise ProviderConfigurationError(f"Payment provider '{name}' is not configured in settings.PAYMENT_PROVIDERS")
    
    config = provider_configs[name]
    
    if 'class' not in config:
        raise ProviderConfigurationError(f"Payment provider '{name}' is missing 'class' in configuration")
    
    try:
        provider_class = import_string(config['class'])
    except ImportError as e:
        raise ProviderConfigurationError(f"Could not import provider class '{config['class']}': {e}")
    
    provider = provider_class(config)
    _provider_cache[name] = provider
    
    return provider


def get_customer_provider(customer_pk: int, customer_type: str) -> Optional[PaymentProvider]:
    """
    Get the provider for an existing customer's subscription.
    
    This looks up the customer's standing subscription and returns
    the provider that manages it.
    
    Args:
        customer_pk: Customer primary key
        customer_type: Customer type ('Registrar' or 'Individual')
        
    Returns:
        PaymentProvider instance if customer has a standing subscription, else None
    """
    # Import here to avoid circular imports
    from ..models import SubscriptionAgreement
    
    sa = SubscriptionAgreement.customer_standing_subscription(customer_pk, customer_type)
    if sa:
        return get_provider(sa.payment_provider)
    return None


def get_checkout_provider(customer_pk: int, customer_type: str) -> PaymentProvider:
    """
    Get the provider to use for checkout.
    
    First checks if the customer has an existing subscription (use that provider).
    Otherwise, probes providers in the configured order until one is available.
    
    Args:
        customer_pk: Customer primary key
        customer_type: Customer type ('Registrar' or 'Individual')
        
    Returns:
        PaymentProvider instance to use for checkout
        
    Raises:
        NoProviderAvailable: If no provider is available for new subscriptions
    """
    # First check if customer has existing subscription
    existing_provider = get_customer_provider(customer_pk, customer_type)
    if existing_provider:
        logger.info(
            "Using existing provider '%s' for %s %s",
            existing_provider.name, customer_type, customer_pk
        )
        return existing_provider
    
    # Probe providers in configured order for new subscriptions
    checkout_providers = getattr(settings, 'CHECKOUT_PROVIDERS', ['cybersource_legacy'])
    
    for provider_name in checkout_providers:
        try:
            provider = get_provider(provider_name)
            if provider.can_handle_new_subscription():
                logger.info(
                    "Selected provider '%s' for new subscription for %s %s",
                    provider_name, customer_type, customer_pk
                )
                return provider
            else:
                logger.debug(
                    "Provider '%s' cannot handle new subscriptions, trying next",
                    provider_name
                )
        except ProviderConfigurationError as e:
            logger.warning("Provider '%s' is misconfigured: %s", provider_name, e)
            continue
    
    raise NoProviderAvailable(
        f"No payment provider available for new subscription. "
        f"Tried: {checkout_providers}"
    )


def clear_provider_cache():
    """
    Clear the provider cache.
    
    Useful for testing or when configuration changes.
    """
    _provider_cache.clear()
