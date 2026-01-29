"""
Payment provider abstraction layer.

This package contains the provider interface and implementations for different
payment processors (CyberSource Legacy, CyberSource REST, Stripe).
"""

from .base import PaymentProvider, CheckoutContext, CallbackResult
from .router import get_provider, get_customer_provider, get_checkout_provider

__all__ = [
    'PaymentProvider',
    'CheckoutContext',
    'CallbackResult',
    'get_provider',
    'get_customer_provider',
    'get_checkout_provider',
]
