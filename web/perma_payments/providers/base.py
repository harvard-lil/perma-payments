"""
Base classes for payment providers.

This module defines the abstract interface that all payment providers must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CheckoutContext:
    """
    Context needed to render a checkout page.
    
    Different providers may use different subsets of these fields:
    - Legacy CyberSource: uses template='redirect.html', post_url, fields_to_post
    - REST CyberSource: uses template='flex_microform.html', client_config
    - Stripe: uses template='stripe_checkout.html', client_config
    """
    template: str  # Template name: 'redirect.html', 'flex_microform.html', 'stripe_checkout.html'
    post_url: Optional[str] = None  # URL to POST form to (for redirect-based flows)
    fields_to_post: dict = field(default_factory=dict)  # Hidden form fields (for redirect-based flows)
    client_config: dict = field(default_factory=dict)  # JavaScript configuration (for embedded/API flows)
    extra_context: dict = field(default_factory=dict)  # Additional template context


@dataclass
class CallbackResult:
    """
    Standardized result from processing a payment callback/webhook.
    
    This provides a uniform interface regardless of which payment provider
    sent the callback.
    """
    success: bool  # Whether the transaction succeeded
    decision: str  # Normalized decision: 'ACCEPT', 'DECLINE', 'ERROR', 'CANCEL', 'REVIEW'
    reason_code: str  # Provider-specific reason code
    message: str  # Human-readable message
    provider_data: dict  # Provider-specific identifiers to store in SubscriptionAgreement.provider_data
    raw_response: dict  # Full response for logging/debugging


class PaymentProvider(ABC):
    """
    Abstract base class for payment providers.
    
    Each payment provider (CyberSource Legacy, CyberSource REST, Stripe)
    must implement this interface to be usable in perma-payments.
    """
    
    # Provider name - must match the key in settings.PAYMENT_PROVIDERS
    name: str = ""
    
    def __init__(self, config: dict):
        """
        Initialize the provider with its configuration.
        
        Args:
            config: Provider-specific configuration from settings.PAYMENT_PROVIDERS
        """
        self.config = config
    
    @abstractmethod
    def get_checkout_context(
        self,
        request_type: str,
        request_data: dict,
        outgoing_transaction: Any,
        return_url: str,
    ) -> CheckoutContext:
        """
        Prepare context for rendering a checkout page.
        
        Args:
            request_type: Type of request ('subscribe', 'purchase', 'change', 'update')
            request_data: Data from the original Perma.cc request
            outgoing_transaction: The OutgoingTransaction model instance
            return_url: URL to return to after payment
            
        Returns:
            CheckoutContext with template and necessary data
        """
        pass
    
    @abstractmethod
    def process_callback(self, request: Any) -> CallbackResult:
        """
        Process a callback/webhook from the payment provider.
        
        Args:
            request: Django HttpRequest containing the callback data
            
        Returns:
            CallbackResult with standardized decision and provider data
        """
        pass
    
    @abstractmethod
    def probe_customer(self, customer_pk: int, customer_type: str) -> bool:
        """
        Check if this provider manages the given customer's subscription.
        
        This is used during the checkout flow to determine which provider
        should handle an existing customer.
        
        Args:
            customer_pk: Customer primary key
            customer_type: Customer type ('Registrar' or 'Individual')
            
        Returns:
            True if this provider manages the customer's subscription
        """
        pass
    
    @abstractmethod
    def can_handle_new_subscription(self) -> bool:
        """
        Check if this provider is available for new subscriptions.
        
        This is used during the checkout flow to determine which provider
        to use when probing in order.
        
        Returns:
            True if this provider can accept new subscriptions
        """
        pass
    
    def get_payment_token(self, subscription_agreement: Any) -> Optional[str]:
        """
        Get the payment token/identifier for an existing subscription.
        
        This is used when the provider needs to reference an existing
        subscription (e.g., for updates or changes).
        
        Args:
            subscription_agreement: SubscriptionAgreement model instance
            
        Returns:
            The payment token/identifier, or None if not found
        """
        return subscription_agreement.provider_data.get('payment_token')
    
    def validate_callback_signature(self, request: Any) -> bool:
        """
        Validate the signature/authenticity of a callback request.
        
        Override this in subclasses that need signature validation.
        
        Args:
            request: Django HttpRequest containing the callback data
            
        Returns:
            True if the callback is authentic
        """
        return True


class ProviderError(Exception):
    """Base exception for provider-related errors."""
    pass


class NoProviderAvailable(ProviderError):
    """Raised when no payment provider is available."""
    pass


class ProviderConfigurationError(ProviderError):
    """Raised when a provider is misconfigured."""
    pass


class CallbackValidationError(ProviderError):
    """Raised when callback validation fails."""
    pass
