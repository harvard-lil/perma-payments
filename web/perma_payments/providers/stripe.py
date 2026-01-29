"""
Stripe payment provider.

This provider implements Stripe Checkout for subscriptions and one-time payments,
using the stripe-python library.
"""

import logging
from typing import Any

from django.conf import settings

from ..models import SubscriptionAgreement
from .base import (
    PaymentProvider,
    CheckoutContext,
    CallbackResult,
    CallbackValidationError,
    ProviderConfigurationError,
)

logger = logging.getLogger(__name__)


class StripeProvider(PaymentProvider):
    """
    Stripe payment provider using Stripe Checkout.
    
    Flow:
    1. We create a Stripe Checkout Session
    2. User is redirected to Stripe's hosted checkout page
    3. After payment, user is redirected back with session_id
    4. Stripe sends webhooks for payment events
    
    For subscriptions, Stripe handles all recurring billing automatically.
    """
    
    name = 'stripe'
    
    def __init__(self, config: dict):
        super().__init__(config)
        
        # Credentials from provider config
        self.secret_key = config.get('secret_key', '')
        self.publishable_key = config.get('publishable_key', '')
        self.webhook_secret = config.get('webhook_secret', '')
        
        # Initialize stripe client
        self._stripe = None
    
    def _get_stripe(self):
        """Get or create stripe client."""
        if self._stripe is not None:
            return self._stripe
        
        if not self.secret_key:
            raise ProviderConfigurationError(
                "Stripe provider requires secret_key"
            )
        
        try:
            import stripe
        except ImportError:
            raise ProviderConfigurationError(
                "Stripe library not installed. Run: pip install stripe"
            )
        
        stripe.api_key = self.secret_key
        self._stripe = stripe
        return stripe
    
    def create_checkout_session(
        self,
        *,
        mode: str,  # 'subscription' or 'payment'
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
        line_items: list[dict] | None = None,
        price_id: str | None = None,
        amount: int | None = None,  # In cents
        currency: str = 'usd',
        metadata: dict | None = None,
    ) -> Any:
        """
        Create a Stripe Checkout Session.
        
        Args:
            mode: 'subscription' for recurring, 'payment' for one-time
            success_url: URL to redirect on success (must include {CHECKOUT_SESSION_ID})
            cancel_url: URL to redirect on cancel
            customer_email: Pre-fill customer email
            line_items: List of line items (if using custom prices)
            price_id: Stripe Price ID (if using pre-created prices)
            amount: Amount in cents (for one-time payments without Price ID)
            currency: Currency code
            metadata: Additional metadata to attach
        
        Returns:
            Stripe Checkout Session object
        """
        stripe = self._get_stripe()
        
        session_params = {
            'mode': mode,
            'success_url': success_url,
            'cancel_url': cancel_url,
        }
        
        if customer_email:
            session_params['customer_email'] = customer_email
        
        if metadata:
            session_params['metadata'] = metadata
        
        # Build line items
        if line_items:
            session_params['line_items'] = line_items
        elif price_id:
            session_params['line_items'] = [{'price': price_id, 'quantity': 1}]
        elif amount:
            session_params['line_items'] = [{
                'price_data': {
                    'currency': currency,
                    'unit_amount': amount,
                    'product_data': {
                        'name': 'Perma.cc Subscription' if mode == 'subscription' else 'Perma.cc Purchase',
                    },
                    'recurring': {'interval': 'month'} if mode == 'subscription' else None,
                },
                'quantity': 1,
            }]
            # Remove None recurring for one-time payments
            if mode != 'subscription':
                del session_params['line_items'][0]['price_data']['recurring']
        else:
            raise ValueError("Must provide line_items, price_id, or amount")
        
        return stripe.checkout.Session.create(**session_params)
    
    def get_checkout_context(
        self,
        request_type: str,
        request_data: dict,
        outgoing_transaction: Any,
        return_url: str,
    ) -> CheckoutContext:
        """
        Prepare context for Stripe Checkout.
        
        Creates a Checkout Session and returns context with the session ID
        for the frontend to redirect to Stripe.
        """
        stripe = self._get_stripe()
        
        # Build URLs
        base_url = return_url.rstrip('/')
        success_url = f"{base_url}/callback/stripe/?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/cancel/"
        
        # Build metadata
        metadata = {
            'customer_pk': str(outgoing_transaction.customer_pk),
            'customer_type': outgoing_transaction.customer_type,
            'transaction_uuid': str(outgoing_transaction.transaction_uuid),
            'request_type': request_type,
        }
        
        if hasattr(outgoing_transaction, 'reference_number'):
            metadata['reference_number'] = outgoing_transaction.reference_number
        
        # Determine mode and amount
        if request_type in ('subscribe', 'change'):
            mode = 'subscription'
            # Convert decimal to cents
            amount = int(float(outgoing_transaction.recurring_amount) * 100)
            
            # Determine interval from frequency
            frequency = getattr(outgoing_transaction, 'recurring_frequency', 'monthly')
            if frequency == 'annually':
                interval = 'year'
            else:
                interval = 'month'
            
            line_items = [{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': amount,
                    'product_data': {
                        'name': f'Perma.cc {outgoing_transaction.customer_type} Subscription',
                        'metadata': metadata,
                    },
                    'recurring': {'interval': interval},
                },
                'quantity': 1,
            }]
        else:  # purchase
            mode = 'payment'
            amount = int(float(outgoing_transaction.amount) * 100)
            line_items = [{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': amount,
                    'product_data': {
                        'name': 'Perma.cc Link Purchase',
                        'metadata': metadata,
                    },
                },
                'quantity': 1,
            }]
        
        # Create Checkout Session
        session = stripe.checkout.Session.create(
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=line_items,
            metadata=metadata,
        )
        
        logger.info(
            "Created Stripe Checkout Session %s for %s %s",
            session.id, outgoing_transaction.customer_type, outgoing_transaction.customer_pk
        )
        
        return CheckoutContext(
            template='stripe_checkout.html',
            client_config={
                'session_id': session.id,
                'publishable_key': self.publishable_key,
            },
            extra_context={
                'checkout_url': session.url,
            },
        )
    
    def process_callback(self, request: Any) -> CallbackResult:
        """
        Process callback from Stripe Checkout completion.
        
        This handles the redirect back from Stripe with session_id.
        """
        stripe = self._get_stripe()
        
        session_id = request.GET.get('session_id') or request.POST.get('session_id')
        
        if not session_id:
            return CallbackResult(
                success=False,
                decision='ERROR',
                reason_code='MISSING_SESSION_ID',
                message='Missing session_id',
                provider_data={},
                raw_response=dict(request.GET),
            )
        
        try:
            # Retrieve the session
            session = stripe.checkout.Session.retrieve(
                session_id,
                expand=['subscription', 'customer']
            )
            
            if session.payment_status != 'paid':
                return CallbackResult(
                    success=False,
                    decision='DECLINE',
                    reason_code='PAYMENT_NOT_COMPLETED',
                    message=f'Payment status: {session.payment_status}',
                    provider_data={},
                    raw_response=session.to_dict(),
                )
            
            # Build provider data
            provider_data = {
                'customer_id': session.customer if isinstance(session.customer, str) else session.customer.id,
                'session_id': session.id,
            }
            
            if session.subscription:
                sub = session.subscription
                provider_data['subscription_id'] = sub if isinstance(sub, str) else sub.id
            
            if session.payment_intent:
                provider_data['payment_intent_id'] = session.payment_intent
            
            return CallbackResult(
                success=True,
                decision='ACCEPT',
                reason_code='100',
                message='Payment successful',
                provider_data=provider_data,
                raw_response=session.to_dict(),
            )
            
        except stripe.error.StripeError as e:
            logger.error("Stripe error processing callback: %s", e)
            return CallbackResult(
                success=False,
                decision='ERROR',
                reason_code='STRIPE_ERROR',
                message=str(e),
                provider_data={},
                raw_response={'error': str(e)},
            )
    
    def process_webhook(self, request: Any) -> CallbackResult:
        """
        Process a Stripe webhook event.
        
        Webhooks are used for asynchronous events like:
        - invoice.paid (subscription renewed)
        - customer.subscription.deleted (subscription canceled)
        - invoice.payment_failed (payment failed)
        """
        stripe = self._get_stripe()
        
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        
        if not self.webhook_secret:
            raise ProviderConfigurationError("Stripe webhook_secret not configured")
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
        except ValueError:
            raise CallbackValidationError("Invalid webhook payload")
        except stripe.error.SignatureVerificationError:
            raise CallbackValidationError("Invalid webhook signature")
        
        logger.info("Received Stripe webhook: %s", event['type'])
        
        # Handle specific event types
        event_type = event['type']
        data_object = event['data']['object']
        
        if event_type == 'checkout.session.completed':
            return self._handle_checkout_completed(data_object)
        elif event_type == 'invoice.paid':
            return self._handle_invoice_paid(data_object)
        elif event_type == 'invoice.payment_failed':
            return self._handle_invoice_failed(data_object)
        elif event_type == 'customer.subscription.deleted':
            return self._handle_subscription_deleted(data_object)
        else:
            # Acknowledge but don't process unknown events
            return CallbackResult(
                success=True,
                decision='ACCEPT',
                reason_code='WEBHOOK_RECEIVED',
                message=f'Webhook {event_type} received',
                provider_data={},
                raw_response=event,
            )
    
    def _handle_checkout_completed(self, session: dict) -> CallbackResult:
        """Handle checkout.session.completed webhook."""
        provider_data = {
            'customer_id': session.get('customer'),
            'session_id': session.get('id'),
        }
        
        if session.get('subscription'):
            provider_data['subscription_id'] = session['subscription']
        
        return CallbackResult(
            success=True,
            decision='ACCEPT',
            reason_code='CHECKOUT_COMPLETED',
            message='Checkout completed',
            provider_data=provider_data,
            raw_response=session,
        )
    
    def _handle_invoice_paid(self, invoice: dict) -> CallbackResult:
        """Handle invoice.paid webhook (subscription renewal)."""
        return CallbackResult(
            success=True,
            decision='ACCEPT',
            reason_code='INVOICE_PAID',
            message='Invoice paid',
            provider_data={
                'customer_id': invoice.get('customer'),
                'subscription_id': invoice.get('subscription'),
                'invoice_id': invoice.get('id'),
            },
            raw_response=invoice,
        )
    
    def _handle_invoice_failed(self, invoice: dict) -> CallbackResult:
        """Handle invoice.payment_failed webhook."""
        return CallbackResult(
            success=False,
            decision='DECLINE',
            reason_code='PAYMENT_FAILED',
            message='Payment failed',
            provider_data={
                'customer_id': invoice.get('customer'),
                'subscription_id': invoice.get('subscription'),
                'invoice_id': invoice.get('id'),
            },
            raw_response=invoice,
        )
    
    def _handle_subscription_deleted(self, subscription: dict) -> CallbackResult:
        """Handle customer.subscription.deleted webhook."""
        return CallbackResult(
            success=True,
            decision='CANCEL',
            reason_code='SUBSCRIPTION_DELETED',
            message='Subscription canceled',
            provider_data={
                'customer_id': subscription.get('customer'),
                'subscription_id': subscription.get('id'),
            },
            raw_response=subscription,
        )
    
    def cancel_subscription(self, subscription_id: str) -> dict:
        """Cancel a Stripe subscription."""
        stripe = self._get_stripe()
        
        logger.info("Canceling Stripe subscription: %s", subscription_id)
        
        subscription = stripe.Subscription.delete(subscription_id)
        return subscription.to_dict()
    
    def probe_customer(self, customer_pk: int, customer_type: str) -> bool:
        """Check if this provider manages the given customer's subscription."""
        sa = SubscriptionAgreement.customer_standing_subscription(customer_pk, customer_type)
        return sa is not None and sa.payment_provider == self.name
    
    def can_handle_new_subscription(self) -> bool:
        """Check if this provider is properly configured."""
        return all([
            self.secret_key,
            self.publishable_key,
        ])
    
    def get_payment_token(self, subscription_agreement: Any) -> str | None:
        """Get the Stripe subscription ID."""
        return subscription_agreement.provider_data.get('subscription_id')
