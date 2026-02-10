"""
Base classes for payment providers.

This module defines the abstract interface that all payment providers must implement.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from perma_payments.models import OutgoingTransaction

logger = logging.getLogger(__name__)




class PaymentProvider(ABC):
    """
    Abstract base class for payment providers.
    
    Each payment provider must implement this interface to be usable in perma-payments.
    """
    
    # Provider name - must match the key in settings.PAYMENT_PROVIDERS
    name: str = ""
    
    # Whether this provider supports programmatic subscription cancellation
    supports_cancellation: bool = False
    
    # URL for staff to manually manage subscriptions in the provider's dashboard.
    # Override in providers that require manual cancellation (e.g., CyberSource Legacy).
    # None means the provider either supports programmatic cancellation or has no dashboard.
    manual_cancellation_url: str | None = None
    
    def __init__(self, config: dict):
        """
        Initialize the provider with its configuration.
        
        Args:
            config: Provider-specific configuration from settings.PAYMENT_PROVIDERS
        """
        self.config = config
    
    @abstractmethod
    def checkout_subscribe(
        self,
        request: HttpRequest,
        s_request: Any,
    ) -> HttpResponse:
        """
        Handle a new subscription checkout.
        
        Args:
            request: Django HttpRequest
            s_request: SubscriptionRequest model instance
            
        Returns:
            HttpResponse (redirect or rendered page)
        """
        pass
    
    @abstractmethod
    def checkout_purchase(
        self,
        request: HttpRequest,
        p_request: Any,
    ) -> HttpResponse:
        """
        Handle a one-time purchase checkout.
        
        Args:
            request: Django HttpRequest
            p_request: PurchaseRequest model instance
            
        Returns:
            HttpResponse (redirect or rendered page)
        """
        pass
    
    @abstractmethod
    def checkout_change(
        self,
        request: HttpRequest,
        c_request: Any,
    ) -> HttpResponse:
        """
        Handle a subscription change checkout.
        
        Args:
            request: Django HttpRequest
            c_request: ChangeRequest model instance
            
        Returns:
            HttpResponse (redirect or rendered page)
        """
        pass
    
    @abstractmethod
    def checkout_update(
        self,
        request: HttpRequest,
        u_request: Any,
    ) -> HttpResponse:
        """
        Handle a payment info update checkout.
        
        Args:
            request: Django HttpRequest
            u_request: UpdateRequest model instance
            
        Returns:
            HttpResponse (redirect or rendered page)
        """
        pass
    
    @abstractmethod
    def handle_webhook(self, request: HttpRequest) -> str | HttpResponse:
        """
        Handle a webhook/callback from the payment provider.
        
        This method handles two types of requests:
        
        1. User-facing callbacks (browser redirected here after payment):
           - Should return HttpResponseRedirect to PERMA_PAYMENT_SUCCESS_REDIRECT_URL
           - User sees the Perma.cc page after payment completion
        
        2. Server-to-server webhooks (background notifications):
           - Should return "OK" string (rendered as a simple page)
           - No user involved, just acknowledges receipt
        
        Returns:
            str: Message to display (e.g., "OK" for webhooks)
            HttpResponse: Response to return directly (e.g., redirect for user callbacks)
        
        Raises:
            CallbackValidationError: If validation fails
        """
        pass
    
    def get_success_redirect(self) -> HttpResponseRedirect:
        """Return a redirect to Perma.cc after successful payment."""
        return HttpResponseRedirect(settings.PERMA_PAYMENT_SUCCESS_REDIRECT_URL)
    
    def get_cancel_redirect(self) -> HttpResponseRedirect:
        """Return a redirect to Perma.cc after canceled payment."""
        return HttpResponseRedirect(settings.PERMA_PAYMENT_CANCELED_REDIRECT_URL)

    def get_outgoing_transaction(self, transaction_uuid: str) -> OutgoingTransaction:
        """Retrieve OutgoingTransaction from a webhook callback."""
        if not transaction_uuid:
            raise CallbackValidationError("No transaction UUID found in callback")
        outgoing_transaction = OutgoingTransaction.objects.filter(transaction_uuid=transaction_uuid).first()
        if not outgoing_transaction:
            raise CallbackValidationError(f"No transaction found for UUID: {transaction_uuid}")
        return outgoing_transaction
    
    @abstractmethod
    def has_credentials(self) -> bool:
        """
        Check if credentials are configured (non-empty).
        
        This is a fast check that only verifies credentials exist locally,
        without making any API calls.
        
        Returns:
            True if all required credentials are present
        """
        pass
    
    def probe_credentials(self) -> bool:
        """
        Probe the upstream API to verify credentials are valid and working.
        
        This makes an actual API call to verify the credentials work.
        Override in providers that support probing. Default returns True
        (assumes credentials work if they exist).
        
        Returns:
            True if the API call succeeds
            
        Raises:
            May raise provider-specific exceptions on failure
        """
        return True
    
    def cancel_subscription(self, subscription_id: str) -> dict:
        """
        Cancel a subscription by ID.
        
        Override this method in providers that support programmatic cancellation,
        and set supports_cancellation = True.
        
        Args:
            subscription_id: Provider-specific subscription identifier
            
        Returns:
            Provider-specific response data
            
        Raises:
            NotImplementedError: If the provider doesn't support programmatic cancellation
        """
        raise NotImplementedError(
            f"Provider '{self.name}' does not support programmatic subscription cancellation"
        )
    
    def can_handle_new_subscription(self) -> bool:
        """
        Check if this provider is available for new subscriptions.
        
        This is used during the checkout flow to determine which provider
        to use when probing in order.
        
        If settings.PROBE_PROVIDER_CREDENTIALS is True, this will make an
        API call to verify credentials actually work, not just that they exist.
        This is useful when expecting a new provider to come online soon.
        
        Returns:
            True if this provider can accept new subscriptions
        """
        if not self.has_credentials():
            return False
        
        if getattr(settings, 'PROBE_PROVIDER_CREDENTIALS', False):
            try:
                result = self.probe_credentials()
                if not result:
                    logger.info(
                        "Provider '%s' credential probe returned False",
                        self.name
                    )
                return result
            except Exception as e:
                logger.info(
                    "Provider '%s' credential probe failed: %s",
                    self.name, e
                )
                return False
        
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

    def __init__(self, display_message: str):
        self.display_message = display_message
        super().__init__(display_message)
