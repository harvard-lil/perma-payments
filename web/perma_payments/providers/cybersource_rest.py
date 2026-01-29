"""
CyberSource REST API payment provider.

This provider implements the CyberSource REST API with Flex Microform for
embedded payment collection, Token Management Service (TMS) for customer
tokens, and Recurring Billing API for subscriptions.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.conf import settings

from ..models import SubscriptionAgreement
from .base import (
    PaymentProvider,
    CheckoutContext,
    CallbackResult,
    ProviderConfigurationError,
)

logger = logging.getLogger(__name__)


def _del_none(d: dict) -> dict:
    """Remove None values from dict (required by CyberSource SDK)."""
    for key, value in list(d.items()):
        if value is None:
            del d[key]
        elif isinstance(value, dict):
            _del_none(value)
    return d


@dataclass
class TokenResult:
    """Result of tokenizing a transient token."""
    customer_id: str
    payment_instrument_id: str | None
    transaction_id: str
    status: str


@dataclass
class SubscriptionResult:
    """Result of creating a subscription."""
    subscription_id: str
    status: str


class CybersourceRestProvider(PaymentProvider):
    """
    CyberSource REST API provider with Flex Microform.
    
    This is the modern API-based flow where:
    1. We generate a capture context JWT
    2. Frontend uses Flex Microform JS to collect card data in an iframe
    3. Flex creates a transient token
    4. We create a TMS customer token from the transient token
    5. We create a recurring billing subscription
    
    This approach keeps card data off our servers (PCI compliance) while
    giving us full programmatic control over subscription management.
    """
    
    name = 'cybersource_rest'
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.mode = config.get('mode', 'test')
        
        # Credentials from provider config
        self.merchant_id = config.get('merchant_id', '')
        self.key_id = config.get('key_id', '')
        self.shared_secret = config.get('shared_secret', '')
        
        # API host
        if self.mode == 'prod':
            self.api_host = 'api.cybersource.com'
        else:
            self.api_host = 'apitest.cybersource.com'
        
        # SDK config will be built lazily
        self._sdk_config = None
    
    def _get_sdk_config(self) -> dict:
        """Build SDK configuration dict."""
        if self._sdk_config is not None:
            return self._sdk_config
        
        if not all([self.merchant_id, self.key_id, self.shared_secret]):
            raise ProviderConfigurationError(
                "CyberSource REST provider requires merchant_id, key_id, and shared_secret"
            )
        
        # Import SDK here to avoid import errors when SDK is not installed
        try:
            from CyberSource.logging.log_configuration import LogConfiguration
        except ImportError:
            raise ProviderConfigurationError(
                "CyberSource SDK not installed. Run: pip install cybersource-rest-client-python"
            )
        
        # Set up logging
        log_config = LogConfiguration()
        log_config.set_enable_log(True)
        log_config.set_log_directory(os.path.join(os.getcwd(), "Logs"))
        log_config.set_log_file_name("cybs_sdk")
        log_config.set_log_maximum_size(10487560)
        log_config.set_log_level("Info")
        log_config.set_enable_masking(True)
        
        self._sdk_config = {
            "authentication_type": "http_signature",
            "merchantid": self.merchant_id,
            "run_environment": self.api_host,
            "merchant_keyid": self.key_id,
            "merchant_secretkey": self.shared_secret,
            "timeout": 30000,  # 30 seconds in milliseconds
            # These are required by the SDK even for http_signature auth (SDK bug)
            "key_alias": self.merchant_id,
            "key_password": self.merchant_id,
            "key_file_name": self.merchant_id,
            "keys_directory": os.getcwd(),
            "log_config": log_config,
        }
        
        return self._sdk_config
    
    def generate_capture_context(
        self,
        target_origins: list[str],
        allowed_card_networks: list[str] | None = None,
    ) -> str:
        """
        Generate a capture context JWT for Flex Microform.
        
        Args:
            target_origins: List of origins where payment form will be hosted
            allowed_card_networks: Card networks to accept
        
        Returns:
            Capture context JWT string
        """
        from CyberSource import GenerateCaptureContextRequest, MicroformIntegrationApi
        
        if allowed_card_networks is None:
            allowed_card_networks = ["VISA", "MASTERCARD", "AMEX", "DISCOVER"]
        
        request_obj = GenerateCaptureContextRequest(
            client_version="v2",
            target_origins=target_origins,
            allowed_card_networks=allowed_card_networks,
            allowed_payment_types=["CARD"],
        )
        
        request_dict = _del_none(request_obj.__dict__)
        request_json = json.dumps(request_dict)
        
        logger.info("Generating capture context for origins: %s", target_origins)
        
        api_instance = MicroformIntegrationApi(self._get_sdk_config())
        return_data, status, body = api_instance.generate_capture_context(request_json)
        
        logger.info("Capture context generated (status=%s)", status)
        return return_data  # JWT string
    
    def create_customer_token(
        self,
        transient_token: str,
        reference_code: str,
        bill_to: dict | None = None,
    ) -> TokenResult:
        """
        Create a TMS customer token from a transient token (Flex JWT).
        
        Creates an authorization hold for $1.00 (validates card without capturing).
        
        Args:
            transient_token: JWT from Flex Microform
            reference_code: Merchant reference code
            bill_to: Optional billing address dict
        
        Returns:
            TokenResult with customer_id and payment_instrument_id
        """
        from CyberSource import (
            CreatePaymentRequest,
            PaymentsApi,
            Ptsv2paymentsClientReferenceInformation,
            Ptsv2paymentsOrderInformation,
            Ptsv2paymentsOrderInformationAmountDetails,
            Ptsv2paymentsOrderInformationBillTo,
            Ptsv2paymentsProcessingInformation,
            Ptsv2paymentsTokenInformation,
        )
        
        client_ref = Ptsv2paymentsClientReferenceInformation(code=reference_code)
        
        processing_info = Ptsv2paymentsProcessingInformation(
            action_list=["TOKEN_CREATE"],
            action_token_types=["customer", "paymentInstrument"],
            capture=False,  # Auth only, no capture
        )
        
        amount_details = Ptsv2paymentsOrderInformationAmountDetails(
            total_amount="1.00",
            currency="USD",
        )
        
        # Default billing info if not provided
        if bill_to is None:
            bill_to = {}
        
        bill_to_obj = Ptsv2paymentsOrderInformationBillTo(
            first_name=bill_to.get('first_name', 'Customer'),
            last_name=bill_to.get('last_name', 'Name'),
            email=bill_to.get('email', 'customer@example.com'),
            address1=bill_to.get('address1', '123 Main St'),
            locality=bill_to.get('locality', 'San Francisco'),
            administrative_area=bill_to.get('administrative_area', 'CA'),
            postal_code=bill_to.get('postal_code', '94105'),
            country=bill_to.get('country', 'US'),
        )
        
        order_info = Ptsv2paymentsOrderInformation(
            amount_details=amount_details.__dict__,
            bill_to=bill_to_obj.__dict__,
        )
        
        token_info = Ptsv2paymentsTokenInformation(
            transient_token_jwt=transient_token,
        )
        
        request_obj = CreatePaymentRequest(
            client_reference_information=client_ref.__dict__,
            processing_information=processing_info.__dict__,
            order_information=order_info.__dict__,
            token_information=token_info.__dict__,
        )
        
        request_dict = _del_none(request_obj.__dict__)
        request_json = json.dumps(request_dict)
        
        logger.info("Creating customer token for reference: %s", reference_code)
        
        api_instance = PaymentsApi(self._get_sdk_config())
        return_data, status, body = api_instance.create_payment(request_json)
        
        logger.info("Token created (status=%s, id=%s)", status, return_data.id)
        
        # Extract token IDs
        token_info_response = return_data.token_information or {}
        customer = {}
        payment_instrument = {}
        
        if hasattr(token_info_response, "customer"):
            customer = token_info_response.customer or {}
            if hasattr(customer, "id"):
                customer = {"id": customer.id}
        elif isinstance(token_info_response, dict):
            customer = token_info_response.get("customer", {})
        
        if hasattr(token_info_response, "payment_instrument"):
            payment_instrument = token_info_response.payment_instrument or {}
            if hasattr(payment_instrument, "id"):
                payment_instrument = {"id": payment_instrument.id}
        elif isinstance(token_info_response, dict):
            payment_instrument = token_info_response.get("paymentInstrument", {})
        
        customer_id = customer.get("id") if isinstance(customer, dict) else getattr(customer, "id", None)
        pi_id = payment_instrument.get("id") if isinstance(payment_instrument, dict) else getattr(payment_instrument, "id", None)
        
        if not customer_id:
            raise ValueError(f"No customer token ID in response: {return_data.token_information}")
        
        return TokenResult(
            customer_id=customer_id,
            payment_instrument_id=pi_id,
            transaction_id=return_data.id,
            status=return_data.status or "UNKNOWN",
        )
    
    def create_subscription(
        self,
        customer_token_id: str,
        reference_code: str,
        subscription_name: str,
        start_date: str,  # YYYY-MM-DD
        billing_amount: str,
        billing_period_unit: str = "M",  # M=month, Y=year
        billing_period_length: str = "1",
        currency: str = "USD",
    ) -> SubscriptionResult:
        """
        Create a recurring billing subscription.
        
        BILLING BEHAVIOR:
        - If start_date is today: charges immediately
        - If start_date is future: first charge on start_date
        
        Args:
            customer_token_id: TMS customer token ID
            reference_code: Merchant reference code
            subscription_name: Name for the subscription
            start_date: Start date (YYYY-MM-DD)
            billing_amount: Amount to bill each period
            billing_period_unit: M=month, Y=year
            billing_period_length: Number of units between billings
            currency: Currency code
        
        Returns:
            SubscriptionResult with subscription_id
        """
        from CyberSource import CreateSubscriptionRequest, SubscriptionsApi
        
        request_dict = {
            "client_reference_information": {
                "code": reference_code,
            },
            "processing_information": {
                "commerce_indicator": "recurring",
                "authorization_options": {
                    "initiator": {
                        "type": "merchant",
                    },
                },
            },
            "subscription_information": {
                "name": subscription_name,
                "start_date": start_date,
            },
            "payment_information": {
                "customer": {
                    "id": customer_token_id,
                },
            },
            "plan_information": {
                "billing_period": {
                    "length": billing_period_length,
                    "unit": billing_period_unit,
                },
            },
            "order_information": {
                "amount_details": {
                    "billing_amount": billing_amount,
                    "currency": currency,
                },
            },
        }
        
        request_obj = CreateSubscriptionRequest(**request_dict)
        final_request = _del_none(request_obj.__dict__)
        request_json = json.dumps(final_request)
        
        logger.info("Creating subscription: %s", subscription_name)
        
        api_instance = SubscriptionsApi(self._get_sdk_config())
        return_data, status, body = api_instance.create_subscription(request_json)
        
        logger.info("Subscription created (status=%s, id=%s)", status, return_data.id)
        
        return SubscriptionResult(
            subscription_id=return_data.id,
            status=return_data.status or "UNKNOWN",
        )
    
    def cancel_subscription(self, subscription_id: str) -> dict:
        """Cancel a subscription by ID."""
        from CyberSource import SubscriptionsApi
        
        logger.info("Canceling subscription: %s", subscription_id)
        
        api_instance = SubscriptionsApi(self._get_sdk_config())
        return_data, status, body = api_instance.cancel_subscription(subscription_id)
        
        logger.info("Subscription canceled (status=%s)", status)
        return return_data.to_dict() if hasattr(return_data, "to_dict") else return_data
    
    def get_checkout_context(
        self,
        request_type: str,
        request_data: dict,
        outgoing_transaction: Any,
        return_url: str,
    ) -> CheckoutContext:
        """
        Prepare context for Flex Microform checkout.
        
        Returns context with capture context JWT and client configuration
        for the embedded payment form.
        """
        # Get target origin from return URL or settings
        from urllib.parse import urlparse
        parsed = urlparse(return_url)
        target_origin = f"{parsed.scheme}://{parsed.netloc}"
        
        capture_context = self.generate_capture_context([target_origin])
        
        # Build client config for the frontend
        client_config = {
            'capture_context': capture_context,
            'request_type': request_type,
            'transaction_uuid': str(outgoing_transaction.transaction_uuid),
            'return_url': return_url,
        }
        
        # Add subscription-specific data
        if request_type == 'subscribe':
            client_config.update({
                'reference_number': outgoing_transaction.reference_number,
                'amount': str(outgoing_transaction.amount),
                'recurring_amount': str(outgoing_transaction.recurring_amount),
                'recurring_frequency': outgoing_transaction.recurring_frequency,
                'recurring_start_date': outgoing_transaction.get_formatted_start_date(),
            })
        elif request_type == 'purchase':
            client_config.update({
                'reference_number': outgoing_transaction.reference_number,
                'amount': str(outgoing_transaction.amount),
            })
        
        return CheckoutContext(
            template='flex_microform.html',
            client_config=client_config,
        )
    
    def process_callback(self, request: Any) -> CallbackResult:
        """
        Process callback from Flex Microform completion.
        
        The frontend POSTs the transient token after successful card capture.
        We then create the customer token and subscription.
        """
        data = request.POST
        
        transient_token = data.get('transient_token')
        transaction_uuid = data.get('transaction_uuid')
        request_type = data.get('request_type')
        
        if not transient_token or not transaction_uuid:
            return CallbackResult(
                success=False,
                decision='ERROR',
                reason_code='MISSING_DATA',
                message='Missing transient_token or transaction_uuid',
                provider_data={},
                raw_response=dict(data),
            )
        
        # Find the related request
        from ..models import OutgoingTransaction
        try:
            related_request = OutgoingTransaction.objects.get(transaction_uuid=transaction_uuid)
        except OutgoingTransaction.DoesNotExist:
            return CallbackResult(
                success=False,
                decision='ERROR',
                reason_code='INVALID_TRANSACTION',
                message=f'No transaction found with UUID {transaction_uuid}',
                provider_data={},
                raw_response=dict(data),
            )
        
        try:
            # Create customer token
            reference_code = getattr(related_request, 'reference_number', str(transaction_uuid))
            token_result = self.create_customer_token(
                transient_token=transient_token,
                reference_code=reference_code,
            )
            
            provider_data = {
                'customer_id': token_result.customer_id,
                'payment_instrument_id': token_result.payment_instrument_id,
            }
            
            # If this is a subscription, create it
            if request_type == 'subscribe':
                # Convert frequency to billing period
                frequency = getattr(related_request, 'recurring_frequency', 'monthly')
                if frequency == 'monthly':
                    billing_period_unit = 'M'
                    billing_period_length = '1'
                elif frequency == 'annually':
                    billing_period_unit = 'Y'
                    billing_period_length = '1'
                else:
                    billing_period_unit = 'M'
                    billing_period_length = '1'
                
                # Get start date
                start_date = getattr(related_request, 'recurring_start_date', date.today())
                if hasattr(start_date, 'strftime'):
                    start_date_str = start_date.strftime('%Y-%m-%d')
                else:
                    start_date_str = str(start_date)
                
                subscription_result = self.create_subscription(
                    customer_token_id=token_result.customer_id,
                    reference_code=reference_code,
                    subscription_name=f"{related_request.customer_type}-{related_request.customer_pk}",
                    start_date=start_date_str,
                    billing_amount=str(related_request.recurring_amount),
                    billing_period_unit=billing_period_unit,
                    billing_period_length=billing_period_length,
                )
                
                provider_data['subscription_id'] = subscription_result.subscription_id
            
            return CallbackResult(
                success=True,
                decision='ACCEPT',
                reason_code='100',
                message='Transaction successful',
                provider_data=provider_data,
                raw_response={
                    'token_result': {
                        'customer_id': token_result.customer_id,
                        'payment_instrument_id': token_result.payment_instrument_id,
                        'status': token_result.status,
                    },
                    'subscription_id': provider_data.get('subscription_id'),
                },
            )
            
        except ValueError as e:
            logger.error("Error processing callback: %s", e)
            return CallbackResult(
                success=False,
                decision='ERROR',
                reason_code='PROCESSING_ERROR',
                message=str(e),
                provider_data={},
                raw_response=dict(data),
            )
    
    def probe_customer(self, customer_pk: int, customer_type: str) -> bool:
        """Check if this provider manages the given customer's subscription."""
        sa = SubscriptionAgreement.customer_standing_subscription(customer_pk, customer_type)
        return sa is not None and sa.payment_provider == self.name
    
    def can_handle_new_subscription(self) -> bool:
        """Check if this provider is properly configured."""
        return all([
            self.merchant_id,
            self.key_id,
            self.shared_secret,
        ])
    
    def get_payment_token(self, subscription_agreement: Any) -> str | None:
        """Get the subscription ID for an existing subscription."""
        return subscription_agreement.provider_data.get('subscription_id')
