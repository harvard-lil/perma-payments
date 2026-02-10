"""
Provider router for selecting and instantiating payment providers.

This module handles the logic for:
- Getting a provider by name
- Finding the provider for an existing customer
- Selecting a provider for new subscriptions (with fallback probing)
"""

import logging

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
        ProviderConfigurationError: If the provider is not configured.
    """
    if name not in _provider_cache:
        config = settings.PAYMENT_PROVIDERS.get(name)
        if not config:
            raise ProviderConfigurationError(f"Payment provider '{name}' is not configured in settings.PAYMENT_PROVIDERS")
        class_path = f'perma_payments.providers.{name}.provider_class'
        provider_class = import_string(class_path)
        _provider_cache[name] = provider_class(config)
    
    return _provider_cache[name]


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
    # Import here to avoid circular imports
    from ..models import SubscriptionAgreement
    
    # First check if customer has existing subscription
    sa = SubscriptionAgreement.customer_standing_subscription(customer_pk, customer_type)
    if sa:
        existing_provider = get_provider(sa.payment_provider)
        logger.info(
            "Using existing provider '%s' for %s %s",
            existing_provider.name, customer_type, customer_pk
        )
        return existing_provider
    
    # Probe providers in configured order for new subscriptions
    for provider_name in settings.CHECKOUT_PROVIDERS:
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
    
    raise NoProviderAvailable(
        f"No payment provider available for new subscription. "
        f"Tried: {settings.CHECKOUT_PROVIDERS}"
    )
