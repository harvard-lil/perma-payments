"""
CyberSource Legacy (Secure Acceptance Web/Mobile) payment provider.

This provider implements the redirect-based CyberSource Secure Acceptance
payment flow, where users are redirected to CyberSource's hosted payment page.
"""

import logging
from typing import Any

from django.conf import settings

from ..constants import CS_PAYMENT_URL, CS_TOKEN_UPDATE_URL
from ..models import SubscriptionAgreement
from ..security import prep_for_cybersource, process_cybersource_transmission, InvalidTransmissionException
from .base import (
    PaymentProvider,
    CheckoutContext,
    CallbackResult,
    CallbackValidationError,
)

logger = logging.getLogger(__name__)


# Fields required from CyberSource callback
CALLBACK_FIELDS = [
    'req_transaction_uuid',
    'decision',
    'reason_code',
    'message',
]


class CybersourceLegacyProvider(PaymentProvider):
    """
    CyberSource Secure Acceptance Web/Mobile provider.
    
    This is the legacy redirect-based flow where:
    1. We render a form with signed fields
    2. The form auto-submits to CyberSource
    3. User enters payment info on CyberSource's hosted page
    4. CyberSource POSTs a callback to our server
    """
    
    name = 'cybersource_legacy'
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.mode = config.get('mode', 'test')
        
        # Credentials from provider config
        self.access_key = config.get('access_key', '')
        self.profile_id = config.get('profile_id', '')
        self.secret_key = config.get('secret_key', '')
    
    def get_checkout_context(
        self,
        request_type: str,
        request_data: dict,
        outgoing_transaction: Any,
        return_url: str,
    ) -> CheckoutContext:
        """
        Prepare the signed form fields for CyberSource Secure Acceptance.
        
        Args:
            request_type: 'subscribe', 'purchase', 'change', or 'update'
            request_data: Data from Perma.cc
            outgoing_transaction: SubscriptionRequest, PurchaseRequest, etc.
            return_url: URL for post-payment redirect (not used by CyberSource legacy)
            
        Returns:
            CheckoutContext with redirect template and signed form fields
        """
        if request_type == 'subscribe':
            return self._get_subscribe_context(outgoing_transaction)
        elif request_type == 'purchase':
            return self._get_purchase_context(outgoing_transaction)
        elif request_type == 'change':
            return self._get_change_context(outgoing_transaction, request_data)
        elif request_type == 'update':
            return self._get_update_context(outgoing_transaction, request_data)
        else:
            raise ValueError(f"Unknown request type: {request_type}")
    
    def _get_subscribe_context(self, s_request: Any) -> CheckoutContext:
        """Prepare context for new subscription."""
        signed_fields = {
            'access_key': self.access_key,
            'amount': s_request.amount,
            'currency': s_request.currency,
            'locale': s_request.locale,
            'payment_method': s_request.payment_method,
            'profile_id': self.profile_id,
            'recurring_amount': s_request.recurring_amount,
            'recurring_frequency': s_request.recurring_frequency,
            'recurring_start_date': s_request.get_formatted_start_date(),
            'reference_number': s_request.reference_number,
            'signed_date_time': s_request.get_formatted_datetime(),
            'transaction_type': s_request.transaction_type,
            'transaction_uuid': s_request.transaction_uuid,
        }
        
        return CheckoutContext(
            template='redirect.html',
            post_url=CS_PAYMENT_URL[self.mode],
            fields_to_post=prep_for_cybersource(signed_fields, secret_key=self.secret_key),
        )
    
    def _get_purchase_context(self, p_request: Any) -> CheckoutContext:
        """Prepare context for one-time purchase."""
        signed_fields = {
            'access_key': self.access_key,
            'amount': p_request.amount,
            'currency': p_request.currency,
            'locale': p_request.locale,
            'payment_method': p_request.payment_method,
            'profile_id': self.profile_id,
            'reference_number': p_request.reference_number,
            'signed_date_time': p_request.get_formatted_datetime(),
            'transaction_type': p_request.transaction_type,
            'transaction_uuid': p_request.transaction_uuid,
        }
        
        return CheckoutContext(
            template='redirect.html',
            post_url=CS_PAYMENT_URL[self.mode],
            fields_to_post=prep_for_cybersource(signed_fields, secret_key=self.secret_key),
        )
    
    def _get_change_context(self, c_request: Any, request_data: dict) -> CheckoutContext:
        """Prepare context for subscription change."""
        sa = c_request.subscription_agreement
        s_request = sa.subscription_request
        s_response = s_request.subscription_request_response
        
        signed_fields = {
            'access_key': self.access_key,
            'amount': c_request.amount,
            'currency': c_request.currency,
            'locale': c_request.locale,
            'payment_method': c_request.payment_method,
            'payment_token': s_response.payment_token,
            'profile_id': self.profile_id,
            'recurring_amount': c_request.recurring_amount,
            'reference_number': s_request.reference_number,
            'signed_date_time': c_request.get_formatted_datetime(),
            'transaction_type': c_request.transaction_type,
            'transaction_uuid': c_request.transaction_uuid,
        }
        
        return CheckoutContext(
            template='redirect.html',
            post_url=CS_TOKEN_UPDATE_URL[self.mode],
            fields_to_post=prep_for_cybersource(signed_fields, secret_key=self.secret_key),
        )
    
    def _get_update_context(self, u_request: Any, request_data: dict) -> CheckoutContext:
        """Prepare context for payment info update."""
        sa = u_request.subscription_agreement
        s_request = sa.subscription_request
        s_response = s_request.subscription_request_response
        
        signed_fields = {
            'access_key': self.access_key,
            'allow_payment_token_update': 'true',
            'locale': s_request.locale,
            'payment_method': s_request.payment_method,
            'payment_token': s_response.payment_token,
            'profile_id': self.profile_id,
            'reference_number': s_request.reference_number,
            'signed_date_time': u_request.get_formatted_datetime(),
            'transaction_type': u_request.transaction_type,
            'transaction_uuid': u_request.transaction_uuid,
        }
        
        return CheckoutContext(
            template='redirect.html',
            post_url=CS_TOKEN_UPDATE_URL[self.mode],
            fields_to_post=prep_for_cybersource(signed_fields, secret_key=self.secret_key),
        )
    
    def process_callback(self, request: Any) -> CallbackResult:
        """
        Process a callback from CyberSource Secure Acceptance.
        
        CyberSource POSTs a signed response containing the transaction decision.
        """
        # Determine which fields to require based on what's in the POST
        fields = list(CALLBACK_FIELDS)
        if 'payment_token' in request.POST:
            fields.append('payment_token')
        
        try:
            data = process_cybersource_transmission(request.POST, fields)
        except InvalidTransmissionException as e:
            raise CallbackValidationError(str(e))
        
        # Build provider_data based on what was returned
        provider_data = {}
        if 'payment_token' in data:
            payment_token = data['payment_token']
            # Validate payment token format (should not be 16-digit format-preserving)
            if len(payment_token) == 16 and payment_token.isdigit():
                logger.error(
                    "Received 16-digit format-preserving payment token. "
                    "Perma-Payments does not support this format."
                )
            provider_data['payment_token'] = payment_token
        
        return CallbackResult(
            success=data['decision'] in ('ACCEPT', 'REVIEW'),
            decision=data['decision'],
            reason_code=data['reason_code'],
            message=data['message'],
            provider_data=provider_data,
            raw_response=dict(request.POST),
        )
    
    def probe_customer(self, customer_pk: int, customer_type: str) -> bool:
        """
        Check if this provider manages the given customer's subscription.
        """
        sa = SubscriptionAgreement.customer_standing_subscription(customer_pk, customer_type)
        return sa is not None and sa.payment_provider == self.name
    
    def can_handle_new_subscription(self) -> bool:
        """
        Check if this provider is properly configured.
        """
        return all([
            self.access_key,
            self.profile_id,
            self.secret_key,
        ])
    
    def get_payment_token(self, subscription_agreement: Any) -> str | None:
        """
        Get the payment token for an existing subscription.
        
        For legacy subscriptions, this may be in provider_data or in the
        SubscriptionRequestResponse.
        """
        # First try provider_data (new location)
        token = subscription_agreement.provider_data.get('payment_token')
        if token:
            return token
        
        # Fall back to SubscriptionRequestResponse (old location)
        try:
            s_request = subscription_agreement.subscription_request
            s_response = s_request.subscription_request_response
            return s_response.payment_token
        except AttributeError:
            return None
