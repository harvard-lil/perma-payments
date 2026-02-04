"""
Stripe payment provider.

This provider implements Stripe Checkout for subscriptions and one-time payments,
using the stripe-python library.
"""

import datetime
import logging
from typing import Any

import stripe
from pytz import timezone

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from perma_payments.models import SubscriptionAgreement, SubscriptionRequest, WebhookLog
from perma_payments.providers.base import (
    PaymentProvider,
    CallbackValidationError,
    ProviderConfigurationError,
)
from perma_payments.tests import trace

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
    supports_cancellation = True
    
    def __init__(self, config: dict):
        super().__init__(config)
        
        # Store reference to config for dynamic webhook_secret lookup
        self._config = config
        
        # Credentials from provider config
        self.secret_key = config.get('secret_key', '')
        self.publishable_key = config.get('publishable_key', '')
        self.webhook_secret = config.get('webhook_secret', '')
        
        # Validate key prefixes match environment
        self._validate_key_environment()
        
        # Initialize stripe client
        if self.secret_key:
            stripe.api_key = self.secret_key
    
    def _validate_key_environment(self):
        """Validate that Stripe key prefixes match PROVIDER_ENVIRONMENT setting."""
        env = settings.PROVIDER_ENVIRONMENT
        
        if env == 'test':
            expected_secret_prefix = 'sk_test_'
            expected_publishable_prefix = 'pk_test_'
        elif env == 'production':
            expected_secret_prefix = 'sk_live_'
            expected_publishable_prefix = 'pk_live_'
        else:
            raise ValueError(f"Unknown PROVIDER_ENVIRONMENT: {env}")
        
        if self.secret_key and not self.secret_key.startswith(expected_secret_prefix):
            raise ValueError(
                f"Stripe secret_key prefix doesn't match PROVIDER_ENVIRONMENT={env}. "
                f"Expected prefix '{expected_secret_prefix}', got key starting with "
                f"'{self.secret_key[:8]}...'"
            )
        
        if self.publishable_key and not self.publishable_key.startswith(expected_publishable_prefix):
            raise ValueError(
                f"Stripe publishable_key prefix doesn't match PROVIDER_ENVIRONMENT={env}. "
                f"Expected prefix '{expected_publishable_prefix}', got key starting with "
                f"'{self.publishable_key[:8]}...'"
            )
    
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
    
    def _create_checkout_session(
        self,
        outgoing_transaction: Any,
        base_url: str,
        request_type: str,
        mode: str,
        line_items: list,
        metadata: dict,
        transaction_uuid: str,
    ) -> str:
        """Create Stripe Checkout Session and return the checkout URL."""
        
        # Build URLs using reverse()
        callback_path = reverse('payment_callback', kwargs={'provider_name': 'stripe'})
        success_url = f"{base_url.rstrip('/')}{callback_path}?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = settings.PERMA_SUBSCRIPTION_CANCELED_REDIRECT_URL
        
        # Create Checkout Session
        # client_reference_id is Stripe's native field for linking sessions to our records
        metadata['transaction_uuid'] = transaction_uuid
        session = stripe.checkout.Session.create(
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=line_items,
            metadata=metadata,
            client_reference_id=transaction_uuid,
        )
        
        logger.info(
            "Created Stripe Checkout Session %s for %s %s",
            session.id, outgoing_transaction.customer_type, outgoing_transaction.customer_pk
        )
        
        return session.url
    
    def checkout_subscribe(self, request: HttpRequest, s_request: Any) -> HttpResponse:
        """Handle Stripe subscription checkout."""
        base_url = request.build_absolute_uri('/')
        metadata = {
            'customer_pk': str(s_request.subscription_agreement.customer_pk),
            'customer_type': s_request.subscription_agreement.customer_type,
            'request_type': 'subscribe',
            'reference_number': s_request.reference_number,
        }
        
        # Convert decimal to cents
        amount = int(float(s_request.recurring_amount) * 100)
        
        # Determine interval from frequency
        if s_request.recurring_frequency == 'annually':
            interval = 'year'
        else:
            interval = 'month'
        
        line_items = [{
            'price_data': {
                'currency': 'usd',
                'unit_amount': amount,
                'product_data': {
                    'name': f'Perma.cc {s_request.subscription_agreement.customer_type} Subscription',
                    'metadata': metadata,
                },
                'recurring': {'interval': interval},
            },
            'quantity': 1,
        }]
        
        checkout_url = self._create_checkout_session(
            outgoing_transaction=s_request.subscription_agreement,
            base_url=base_url,
            request_type='subscribe',
            mode='subscription',
            line_items=line_items,
            metadata=metadata,
            transaction_uuid=str(s_request.transaction_uuid),
        )
        return HttpResponseRedirect(checkout_url)
    
    def checkout_purchase(self, request: HttpRequest, p_request: Any) -> HttpResponse:
        """Handle Stripe one-time purchase checkout."""
        base_url = request.build_absolute_uri('/')
        metadata = {
            'customer_pk': str(p_request.customer_pk),
            'customer_type': p_request.customer_type,
            'request_type': 'purchase',
            'reference_number': p_request.reference_number,
        }
        
        amount = int(float(p_request.amount) * 100)
        
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
        
        checkout_url = self._create_checkout_session(
            outgoing_transaction=p_request,
            base_url=base_url,
            request_type='purchase',
            mode='payment',
            line_items=line_items,
            metadata=metadata,
            transaction_uuid=str(p_request.transaction_uuid),
        )
        return HttpResponseRedirect(checkout_url)
    
    def checkout_change(self, request: HttpRequest, c_request: Any) -> HttpResponse:
        """Handle Stripe subscription change checkout."""
        base_url = request.build_absolute_uri('/')
        metadata = {
            'customer_pk': str(c_request.subscription_agreement.customer_pk),
            'customer_type': c_request.subscription_agreement.customer_type,
            'request_type': 'change',
        }
        
        # Convert decimal to cents
        amount = int(float(c_request.recurring_amount) * 100)
        
        line_items = [{
            'price_data': {
                'currency': 'usd',
                'unit_amount': amount,
                'product_data': {
                    'name': f'Perma.cc {c_request.subscription_agreement.customer_type} Subscription',
                    'metadata': metadata,
                },
                'recurring': {'interval': 'month'},
            },
            'quantity': 1,
        }]
        
        checkout_url = self._create_checkout_session(
            outgoing_transaction=c_request.subscription_agreement,
            base_url=base_url,
            request_type='change',
            mode='subscription',
            line_items=line_items,
            metadata=metadata,
            transaction_uuid=str(c_request.transaction_uuid),
        )
        return HttpResponseRedirect(checkout_url)
    
    def checkout_update(self, request: HttpRequest, u_request: Any) -> HttpResponse:
        """
        Handle Stripe payment info update via Billing Portal.
        
        Stripe's Billing Portal is a hosted page where customers can:
        - Update their payment methods
        - View invoices
        - Manage their subscription
        
        We redirect the user there, and Stripe handles the rest. When payment
        methods are updated, Stripe sends webhooks (payment_method.attached, etc.)
        which are logged via WebhookLog.
        """
        sa = u_request.subscription_agreement
        customer_id = (sa.provider_data or {}).get('customer_id')
        
        if not customer_id:
            raise ProviderConfigurationError(
                "No Stripe customer_id found for subscription. "
                "The subscription may have been created with a different provider."
            )
        
        # Create Billing Portal session
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=settings.PERMA_PAYMENT_SUCCESS_REDIRECT_URL,
        )
        
        logger.info(
            "Created Stripe Billing Portal session for customer %s (agreement=%s)",
            customer_id, sa.pk
        )
        
        return HttpResponseRedirect(session.url)
    
    def handle_webhook(self, request: HttpRequest) -> str | HttpResponse:
        """
        Handle Stripe callbacks and webhooks.
        
        This method handles two types of requests:
        
        1. User callbacks (GET with session_id): 
           - User's browser redirected here after Stripe Checkout completes
           - Returns redirect to Perma.cc
        
        2. Server webhooks (POST with Stripe signature):
           - Async events from Stripe (invoice.paid, subscription.deleted, etc.)
           - Returns "OK" to acknowledge
        
        All webhook events are logged to WebhookLog for audit purposes.
        """
        
        # Check if this is a user callback (GET with session_id) or server webhook (POST with signature)
        session_id = request.GET.get('session_id')
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        
        if request.method == 'GET' and session_id:
            # User callback after Stripe Checkout - redirect to Perma.cc
            logger.info("Stripe checkout completed, redirecting user (session=%s)", session_id)
            return self.get_success_redirect()
        
        # Server-to-server webhook
        if not sig_header:
            raise CallbackValidationError("Missing Stripe signature header")
        
        payload = request.body
        
        if not self.webhook_secret:
            raise ProviderConfigurationError("Stripe webhook_secret not configured")
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
        except ValueError:
            trace.log(
                title='Webhook Validation Failed',
                lane='Server',
                data={'error': 'Invalid webhook payload'},
            )
            raise CallbackValidationError("Invalid webhook payload")
        except stripe.error.SignatureVerificationError:
            trace.log(
                title='Webhook Validation Failed',
                lane='Server',
                data={'error': 'Invalid webhook signature'},
            )
            raise CallbackValidationError("Invalid webhook signature")
        
        event_id = event['id']
        event_type = event['type']
        data_object = event['data']['object']
        
        trace.log(
            title='Webhook Signature Valid',
            lane='Server',
            data={
                'event_id': event_id,
                'event_type': event_type,
                'data_object': data_object,
            },
        )
        
        logger.info("Received Stripe webhook: %s (id=%s)", event_type, event_id)
        
        # Handle specific event types and collect result for logging
        agreement = None
        status = 'processed'
        status_message = ''
        
        if event_type == 'checkout.session.completed':
            agreement, status, status_message = self._handle_checkout_completed(data_object)
        elif event_type in ('customer.subscription.created', 'customer.subscription.updated'):
            agreement, status, status_message = self._handle_subscription_updated(data_object, event_type)
        elif event_type in ('invoice.paid', 'invoice.payment_succeeded'):
            agreement, status, status_message = self._handle_invoice_paid(data_object)
        elif event_type == 'invoice.payment_failed':
            agreement, status, status_message = self._handle_invoice_failed(data_object)
        elif event_type == 'customer.subscription.deleted':
            agreement, status, status_message = self._handle_subscription_deleted(data_object)
        elif event_type in ('payment_method.attached', 'customer.source.updated'):
            agreement, status, status_message = self._handle_payment_method_updated(data_object, event_type)
        else:
            # Acknowledge but don't process unknown events
            status = 'ignored'
            status_message = f'Unhandled event type: {event_type}'
            logger.debug("Unhandled Stripe webhook event: %s", event_type)
        
        # Log the webhook event (returns None if duplicate)
        webhook_log = WebhookLog.log_event(
            provider='stripe',
            event_id=event_id,
            event_type=event_type,
            raw_event=dict(event),
            subscription_agreement=agreement,
            status=status,
            status_message=status_message,
        )
        
        # Trace the models that were written
        if webhook_log:
            trace.db(webhook_log, title='WebhookLog', action='Create')
        if agreement:
            trace.db(agreement, title='SubscriptionAgreement (status updated)')

        return "OK"
    
    def _find_agreement_from_metadata(self, metadata: dict | None) -> SubscriptionAgreement | None:
        """
        Find a SubscriptionAgreement from Stripe metadata.
        
        Metadata may contain:
        - transaction_uuid: links to SubscriptionRequest.transaction_uuid
        - customer_pk + customer_type: direct lookup on SubscriptionAgreement
        """
        if not metadata:
            return None
        
        # Try transaction_uuid first (most reliable - set during checkout creation)
        transaction_uuid = metadata.get('transaction_uuid')
        if transaction_uuid:
            try:
                s_request = SubscriptionRequest.objects.select_related(
                    'subscription_agreement'
                ).get(transaction_uuid=transaction_uuid)
                return s_request.subscription_agreement
            except SubscriptionRequest.DoesNotExist:
                pass
        
        # Fall back to customer_pk + customer_type
        customer_pk = metadata.get('customer_pk')
        customer_type = metadata.get('customer_type')
        if customer_pk and customer_type:
            return SubscriptionAgreement.customer_standing_subscription(
                int(customer_pk), customer_type
            )
        
        return None
    
    def _find_agreement_for_subscription_id(self, subscription_id: str) -> SubscriptionAgreement | None:
        """Find a SubscriptionAgreement by Stripe subscription_id in provider_data."""
        if not subscription_id:
            return None
        try:
            return SubscriptionAgreement.objects.get(
                provider_data__subscription_id=subscription_id,
                payment_provider='stripe'
            )
        except SubscriptionAgreement.DoesNotExist:
            return None
    
    def _find_agreement_for_customer_id(self, customer_id: str) -> SubscriptionAgreement | None:
        """Find a SubscriptionAgreement by Stripe customer_id in provider_data."""
        if not customer_id:
            return None
        try:
            # Get the most recently updated agreement for this customer
            return SubscriptionAgreement.objects.filter(
                provider_data__customer_id=customer_id,
                payment_provider='stripe'
            ).order_by('-updated_date').first()
        except SubscriptionAgreement.DoesNotExist:
            return None
    
    def _update_agreement_status(
        self,
        agreement: SubscriptionAgreement,
        status: str,
        paid_through: datetime.datetime | None = None,
    ) -> None:
        """Update a SubscriptionAgreement's status and optionally paid_through."""
        update_fields = ['status']
        agreement.status = status
        
        if paid_through is not None:
            agreement.paid_through = paid_through
            update_fields.append('paid_through')
        
        agreement.save(update_fields=update_fields)
        logger.info(
            "Updated SubscriptionAgreement %s: status=%s, paid_through=%s",
            agreement.pk, status, paid_through
        )
    
    def _timestamp_to_datetime(self, ts: int | None) -> datetime.datetime | None:
        """Convert a Unix timestamp to a timezone-aware datetime."""
        if ts is None:
            return None
        return datetime.datetime.fromtimestamp(ts, tz=timezone(settings.TIME_ZONE))
    
    def _handle_checkout_completed(self, session: dict) -> tuple[SubscriptionAgreement | None, str, str]:
        """
        Handle checkout.session.completed webhook.
        
        This event fires when a customer completes checkout. For subscriptions,
        this is the initial signup. We need to:
        1. Find the SubscriptionAgreement via metadata
        2. Store the Stripe subscription_id and customer_id in provider_data
        3. Mark the agreement as Current
        
        For one-time purchases (request_type=purchase), there is no
        SubscriptionAgreement — the webhook is acknowledged but ignored.
        
        Returns:
            Tuple of (agreement, status, status_message) for WebhookLog
        """
        metadata = session.get('metadata') or {}
        subscription_id = session.get('subscription')
        customer_id = session.get('customer')
        
        # One-time purchases don't have a SubscriptionAgreement
        request_type = metadata.get('request_type')
        if request_type == 'purchase':
            logger.info(
                "Stripe checkout.session.completed for one-time purchase "
                "(reference=%s), no subscription to update",
                metadata.get('reference_number')
            )
            return None, 'ignored', 'One-time purchase, no subscription to update'
        
        # Find the agreement
        agreement = self._find_agreement_from_metadata(metadata)
        if not agreement:
            logger.warning(
                "Stripe checkout.session.completed: could not find SubscriptionAgreement. "
                "metadata=%s", metadata
            )
            return None, 'unmatched', f'Could not find SubscriptionAgreement for metadata={metadata}'
        
        # Update provider_data with Stripe IDs
        provider_data = agreement.provider_data or {}
        if subscription_id:
            provider_data['subscription_id'] = subscription_id
        if customer_id:
            provider_data['customer_id'] = customer_id
        provider_data['session_id'] = session.get('id')
        
        agreement.provider_data = provider_data
        if agreement.payment_provider != 'stripe':
            agreement.payment_provider = 'stripe'
        agreement.status = 'Current'
        agreement.save(update_fields=['provider_data', 'payment_provider', 'status'])
        
        logger.info(
            "Stripe checkout completed for SubscriptionAgreement %s (subscription=%s)",
            agreement.pk, subscription_id
        )
        
        return agreement, 'processed', 'Checkout completed, status=Current'
    
    def _handle_subscription_updated(self, subscription: dict, event_type: str) -> tuple[SubscriptionAgreement | None, str, str]:
        """
        Handle customer.subscription.created and customer.subscription.updated webhooks.
        
        These events help keep provider_data in sync with Stripe. We:
        1. Find the SubscriptionAgreement
        2. Update provider_data with the latest subscription/customer IDs
        
        Returns:
            Tuple of (agreement, status, status_message) for WebhookLog
        """
        subscription_id = subscription.get('id')
        customer_id = subscription.get('customer')
        
        # Try to find the agreement
        agreement = self._find_agreement_from_metadata(subscription.get('metadata'))
        if not agreement:
            agreement = self._find_agreement_for_subscription_id(subscription_id)
        if not agreement:
            agreement = self._find_agreement_for_customer_id(customer_id)
        
        if not agreement:
            logger.warning(
                "Stripe %s: could not find SubscriptionAgreement. "
                "subscription=%s, customer=%s",
                event_type, subscription_id, customer_id
            )
            return None, 'unmatched', f'Could not find SubscriptionAgreement for subscription={subscription_id}'
        
        # Update provider_data
        provider_data = agreement.provider_data or {}
        if subscription_id:
            provider_data['subscription_id'] = subscription_id
        if customer_id:
            provider_data['customer_id'] = customer_id
        
        update_fields = ['provider_data']
        agreement.provider_data = provider_data
        
        if agreement.payment_provider != 'stripe':
            agreement.payment_provider = 'stripe'
            update_fields.append('payment_provider')
        
        agreement.save(update_fields=update_fields)
        
        logger.info(
            "Stripe %s: updated SubscriptionAgreement %s provider_data",
            event_type, agreement.pk
        )
        
        return agreement, 'processed', 'Updated provider_data'
    
    def _handle_invoice_paid(self, invoice: dict) -> tuple[SubscriptionAgreement | None, str, str]:
        """
        Handle invoice.paid webhook (subscription renewal).
        
        This event fires when an invoice is successfully paid. For subscriptions,
        this happens at initial signup and each renewal. We need to:
        1. Find the SubscriptionAgreement
        2. Update status to Current
        3. Update paid_through based on the invoice period
        
        Returns:
            Tuple of (agreement, status, status_message) for WebhookLog
        """
        subscription_id = invoice.get('subscription')
        customer_id = invoice.get('customer')
        invoice_id = invoice.get('id')
        
        # Try multiple methods to find the agreement
        agreement = None
        
        # First try metadata
        metadata = invoice.get('metadata') or {}
        agreement = self._find_agreement_from_metadata(metadata)
        
        # Try subscription_details.metadata (for recurring invoices)
        if not agreement:
            sub_details = invoice.get('subscription_details') or {}
            agreement = self._find_agreement_from_metadata(sub_details.get('metadata'))
        
        # Try line items metadata
        if not agreement:
            lines = invoice.get('lines', {})
            line_data = lines.get('data', []) if isinstance(lines, dict) else []
            for line in line_data:
                agreement = self._find_agreement_from_metadata(line.get('metadata'))
                if agreement:
                    break
        
        # Try subscription_id lookup
        if not agreement and subscription_id:
            agreement = self._find_agreement_for_subscription_id(subscription_id)
        
        # Try customer_id lookup
        if not agreement and customer_id:
            agreement = self._find_agreement_for_customer_id(customer_id)
        
        if not agreement:
            logger.warning(
                "Stripe invoice.paid: could not find SubscriptionAgreement. "
                "invoice=%s, subscription=%s, customer=%s",
                invoice_id, subscription_id, customer_id
            )
            return None, 'unmatched', f'Could not find SubscriptionAgreement for invoice={invoice_id}'
        
        # Calculate paid_through from invoice line items
        paid_through = None
        lines = invoice.get('lines', {})
        line_data = lines.get('data', []) if isinstance(lines, dict) else []
        for line in line_data:
            period = line.get('period') or {}
            end_ts = period.get('end')
            if end_ts is not None:
                candidate = self._timestamp_to_datetime(end_ts)
                if paid_through is None or candidate > paid_through:
                    paid_through = candidate
        
        # Update the agreement
        self._update_agreement_status(agreement, 'Current', paid_through)
        
        logger.info(
            "Stripe invoice.paid for SubscriptionAgreement %s: paid_through=%s",
            agreement.pk, paid_through
        )
        
        return agreement, 'processed', f'Invoice paid, status=Current, paid_through={paid_through}'
    
    def _handle_invoice_failed(self, invoice: dict) -> tuple[SubscriptionAgreement | None, str, str]:
        """
        Handle invoice.payment_failed webhook.
        
        This event fires when a payment attempt fails. We need to:
        1. Find the SubscriptionAgreement
        2. Update status to Hold
        
        Returns:
            Tuple of (agreement, status, status_message) for WebhookLog
        """
        subscription_id = invoice.get('subscription')
        customer_id = invoice.get('customer')
        invoice_id = invoice.get('id')
        
        # Try to find the agreement
        agreement = self._find_agreement_for_subscription_id(subscription_id)
        if not agreement:
            agreement = self._find_agreement_for_customer_id(customer_id)
        
        if not agreement:
            logger.warning(
                "Stripe invoice.payment_failed: could not find SubscriptionAgreement. "
                "invoice=%s, subscription=%s, customer=%s",
                invoice_id, subscription_id, customer_id
            )
            return None, 'unmatched', f'Could not find SubscriptionAgreement for invoice={invoice_id}'
        
        self._update_agreement_status(agreement, 'Hold')
        
        logger.info(
            "Stripe invoice.payment_failed for SubscriptionAgreement %s",
            agreement.pk
        )
        
        return agreement, 'processed', 'Payment failed, status=Hold'
    
    def _handle_subscription_deleted(self, subscription: dict) -> tuple[SubscriptionAgreement | None, str, str]:
        """
        Handle customer.subscription.deleted webhook.
        
        This event fires when a subscription is canceled. We need to:
        1. Find the SubscriptionAgreement
        2. Update status to Canceled
        
        Returns:
            Tuple of (agreement, status, status_message) for WebhookLog
        """
        subscription_id = subscription.get('id')
        customer_id = subscription.get('customer')
        
        # Try to find the agreement
        agreement = self._find_agreement_from_metadata(subscription.get('metadata'))
        if not agreement:
            agreement = self._find_agreement_for_subscription_id(subscription_id)
        if not agreement:
            agreement = self._find_agreement_for_customer_id(customer_id)
        
        if not agreement:
            logger.warning(
                "Stripe customer.subscription.deleted: could not find SubscriptionAgreement. "
                "subscription=%s, customer=%s",
                subscription_id, customer_id
            )
            return None, 'unmatched', f'Could not find SubscriptionAgreement for subscription={subscription_id}'
        
        self._update_agreement_status(agreement, 'Canceled')
        
        logger.info(
            "Stripe subscription.deleted for SubscriptionAgreement %s",
            agreement.pk
        )
        
        return agreement, 'processed', 'Subscription canceled, status=Canceled'
    
    def _handle_payment_method_updated(self, data_object: dict, event_type: str) -> tuple[SubscriptionAgreement | None, str, str]:
        """
        Handle payment_method.attached and customer.source.updated webhooks.
        
        These events fire when a customer updates their payment method, typically
        via the Billing Portal after a checkout_update flow. We:
        1. Find the SubscriptionAgreement by customer_id
        2. Log the event (actual update is handled by Stripe)
        
        Note: We don't need to store the new payment method details - Stripe
        manages payment methods and will use the updated method for future charges.
        
        Returns:
            Tuple of (agreement, status, status_message) for WebhookLog
        """
        # For payment_method.attached, customer is in the object directly
        customer_id = data_object.get('customer')
        
        if not customer_id:
            logger.info(
                "Stripe %s: no customer_id in event, cannot link to subscription",
                event_type
            )
            return None, 'ignored', 'No customer_id in event'
        
        # Find the agreement
        agreement = self._find_agreement_for_customer_id(customer_id)
        
        if not agreement:
            # This is not necessarily an error - the customer may have updated
            # payment info for a subscription we don't track, or this could be
            # a non-subscription customer
            logger.info(
                "Stripe %s: could not find SubscriptionAgreement for customer=%s",
                event_type, customer_id
            )
            return None, 'unmatched', f'No SubscriptionAgreement for customer={customer_id}'
        
        # Log success - Stripe handles the actual payment method storage
        payment_method_id = data_object.get('id', 'unknown')
        payment_method_type = data_object.get('type', 'unknown')
        
        logger.info(
            "Stripe %s: payment method updated for SubscriptionAgreement %s "
            "(payment_method=%s, type=%s)",
            event_type, agreement.pk, payment_method_id, payment_method_type
        )
        
        return agreement, 'processed', f'Payment method updated: {payment_method_type}'
    
    def cancel_subscription(self, subscription_id: str) -> dict:
        """Cancel a Stripe subscription."""
        
        logger.info("Canceling Stripe subscription: %s", subscription_id)
        
        subscription = stripe.Subscription.delete(subscription_id)
        return subscription.to_dict()
    
    def has_credentials(self) -> bool:
        """Check if credentials are configured."""
        return all([
            self.secret_key,
            self.publishable_key,
        ])
    
    def probe_credentials(self) -> bool:
        """
        Probe the Stripe API to verify credentials work.
        
        Makes a lightweight API call (retrieve account info) to verify
        the API key is valid.
        """
        try:
            # This is a read-only call that validates the API key
            stripe.Account.retrieve()
            return True
        except stripe.error.AuthenticationError:
            logger.warning("Stripe credential probe failed: invalid API key")
            return False
        except stripe.error.APIConnectionError as e:
            logger.warning("Stripe credential probe failed: %s", e)
            return False

