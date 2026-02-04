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
from functools import cached_property
from typing import Any

from django.urls import reverse

from CyberSource import (
    MicroformIntegrationApi,
    GenerateCaptureContextRequest,
    SubscriptionsApi,
    CreateSubscriptionRequest,
    CreatePaymentRequest,
    PaymentsApi,
    Ptsv2paymentsClientReferenceInformation,
    Ptsv2paymentsOrderInformation,
    Ptsv2paymentsOrderInformationAmountDetails,
    Ptsv2paymentsOrderInformationBillTo,
    Ptsv2paymentsProcessingInformation,
    Ptsv2paymentsTokenInformation
)
from CyberSource.rest import ApiException
from CyberSource.utilities.flex.CaptureContextParsingUtility import parse_capture_context_response
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from perma_payments.models import Response
from perma_payments.providers.base import (
    PaymentProvider,
    ProviderConfigurationError,
    CallbackValidationError,
)
from perma_payments.tests import trace

logger = logging.getLogger(__name__)


def _del_none(d: dict) -> dict:
    """Remove None values from dict (required by CyberSource SDK)."""
    for key, value in list(d.items()):
        if value is None:
            del d[key]
        elif isinstance(value, dict):
            _del_none(value)
    return d


def _format_cs_request(request_obj) -> [dict, str]:
    """Format a Cybersource request object for CyberSource."""
    request_dict = request_obj.__dict__
    _del_none(request_dict)
    request_json = json.dumps(request_dict)
    return request_dict, request_json


class CybersourceApiError(Exception):
    """Error from CyberSource API (non-2xx response)."""
    def __init__(self, message: str, status: int = None, reason: str = None, body: str = None):
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.body = body


def _call_cybersource(title: str, method, *args, error_class=None, **kwargs):
    """
    Call a CyberSource API method and convert errors to a clean exception.
    
    Args:
        title: Description for logging/tracing (e.g., "Token Creation")
        method: The SDK method to call
        *args: Arguments to pass to the method
        error_class: Exception class to raise on error (default: CybersourceApiError)
        **kwargs: Keyword arguments to pass to the method
    
    Returns:
        The result from the SDK method (typically a (return_data, status, body) tuple)
        
    Raises:
        error_class (or CybersourceApiError): If the API returns a non-2xx response
    """
    if error_class is None:
        error_class = CybersourceApiError
    try:
        return method(*args, **kwargs)
    except ApiException as e:
        logger.error("CyberSource %s failed: %s", title, e)
        trace.network_response(
            from_lane='Cybersource Rest',
            to_lane='Server',
            status=e.status,
            body={'error': e.reason, 'body': e.body},
            title=f'{title} Failed',
        )
        raise error_class(f"{title} failed: {e.reason}") from e


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

API_HOSTS = {
    "test": "apitest.cybersource.com",
    "prod": "api.cybersource.com"
}


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
    supports_cancellation = True
    
    def __init__(self, config: dict):
        super().__init__(config)

        # Credentials from provider config
        self.merchant_id = config.get('merchant_id', '')
        self.key_id = config.get('key_id', '')
        self.shared_secret = config.get('shared_secret', '')
        
    @cached_property
    def _sdk_config(self) -> dict:
        """Build SDK configuration dict."""
        if not self.has_credentials():
            raise ProviderConfigurationError(
                "CyberSource REST provider requires merchant_id, key_id, and shared_secret"
            )
        
        return {
            "authentication_type": "http_signature",
            "merchantid": self.merchant_id,
            "run_environment": API_HOSTS[settings.PROVIDER_ENVIRONMENT],
            "merchant_keyid": self.key_id,
            "merchant_secretkey": self.shared_secret,
            "timeout": 30000,  # 30 seconds in milliseconds
            # These are required by the SDK even for http_signature auth (SDK bug)
            "key_alias": self.merchant_id,
            "key_password": self.merchant_id,
            "key_file_name": self.merchant_id,
            "keys_directory": os.getcwd(),
        }

    @cached_property
    def microform_api(self) -> MicroformIntegrationApi:
        return MicroformIntegrationApi(self._sdk_config)

    @cached_property
    def payments_api(self) -> PaymentsApi:
        return PaymentsApi(self._sdk_config)

    @cached_property
    def subscriptions_api(self) -> SubscriptionsApi:
        return SubscriptionsApi(self._sdk_config)

    def generate_capture_context(
        self,
        target_origins: list[str],
    ) -> str:
        """
        Generate a capture context JWT for Flex Microform.
        
        Args:
            target_origins: List of origins where payment form will be hosted
        
        Returns:
            Capture context JWT string
        """
        allowed_card_networks = self.config['allowed_card_networks']
        
        request_obj = GenerateCaptureContextRequest(
            client_version="v2",
            target_origins=target_origins,
            allowed_card_networks=allowed_card_networks,
            allowed_payment_types=["CARD"],
        )
        
        request_dict, request_json = _format_cs_request(request_obj)
        
        logger.info("Generating capture context for origins: %s", target_origins)
        trace.network_request(
            from_lane='Server',
            to_lane='Cybersource Rest',
            method='POST',
            url=f"https://{API_HOSTS[settings.PROVIDER_ENVIRONMENT]}/microform/v2/sessions",
            body=request_dict,
            title='Generate Capture Context',
        )
        return_data, status, body = self.microform_api.generate_capture_context(request_json)
        
        trace.network_response(
            from_lane='Cybersource Rest',
            to_lane='Server',
            status=status,
            body={'capture_context_jwt': return_data[:50] + '...' if len(return_data) > 50 else return_data},
            title='Capture Context Response',
        )
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
        
        request_dict, request_json = _format_cs_request(request_obj)
        
        logger.info("Creating customer token for reference: %s", reference_code)
        trace.network_request(
            from_lane='Server',
            to_lane='Cybersource Rest',
            method='POST',
            url=f"https://{API_HOSTS[settings.PROVIDER_ENVIRONMENT]}/pts/v2/payments",
            body=request_dict,
            title='Create Customer Token',
        )
        
        return_data, status, body = _call_cybersource(
            'Token Creation', self.payments_api.create_payment, request_json,
            error_class=CallbackValidationError,
        )
        
        response_dict = return_data.to_dict() if hasattr(return_data, 'to_dict') else {'raw': str(return_data)}
        trace.network_response(
            from_lane='Cybersource Rest',
            to_lane='Server',
            status=status,
            body=response_dict,
            title='Token Created',
        )
        logger.info("Token created (status=%s, id=%s)", status, return_data.id)
        
        # Extract token IDs - SDK always returns typed objects
        token_info = return_data.token_information
        if not token_info:
            raise ValueError(f"No token_information in response: {return_data}")

        customer = token_info.customer
        if not customer or not customer.id:
            raise ValueError(f"No customer token ID in response: {token_info}")

        payment_instrument = token_info.payment_instrument
        pi_id = payment_instrument.id if payment_instrument else None
        
        return TokenResult(
            customer_id=customer.id,
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
        
        request_obj = CreateSubscriptionRequest(
            client_reference_information={
                "code": reference_code,
            },
            processing_information={
                "commerce_indicator": "recurring",
                "authorization_options": {
                    "initiator": {
                        "type": "merchant",
                    },
                },
            },
            subscription_information={
                "name": subscription_name,
                "start_date": start_date,
            },
            payment_information={
                "customer": {
                    "id": customer_token_id,
                },
            },
            plan_information={
                "billing_period": {
                    "length": billing_period_length,
                    "unit": billing_period_unit,
                },
            },
            order_information={
                "amount_details": {
                    "billing_amount": billing_amount,
                    "currency": currency,
                },
            },
        )
        request_dict, request_json = _format_cs_request(request_obj)
        
        logger.info("Creating subscription: %s", subscription_name)
        trace.network_request(
            from_lane='Server',
            to_lane='Cybersource Rest',
            method='POST',
            url=f"https://{API_HOSTS[settings.PROVIDER_ENVIRONMENT]}/rbs/v1/subscriptions",
            body=request_dict,
            title='Create Subscription',
        )
        
        return_data, status, body = _call_cybersource(
            'Subscription Creation', self.subscriptions_api.create_subscription, request_json,
            error_class=CallbackValidationError,
        )
        
        response_dict = return_data.to_dict() if hasattr(return_data, 'to_dict') else {'raw': str(return_data)}
        trace.network_response(
            from_lane='Cybersource Rest',
            to_lane='Server',
            status=status,
            body=response_dict,
            title='Subscription Created',
        )
        logger.info("Subscription created (status=%s, id=%s)", status, return_data.id)
        
        return SubscriptionResult(
            subscription_id=return_data.id,
            status=return_data.status or "UNKNOWN",
        )
    
    def cancel_subscription(self, subscription_id: str) -> dict:
        """Cancel a subscription by ID.
        
        Raises:
            CybersourceApiError: If the API returns a non-2xx response
        """
        logger.info("Canceling subscription: %s", subscription_id)
        
        return_data, status, body = _call_cybersource(
            'Subscription Cancellation', self.subscriptions_api.cancel_subscription, subscription_id
        )
        
        logger.info("Subscription canceled (status=%s)", status)
        return return_data.to_dict() if hasattr(return_data, "to_dict") else return_data
    
    def _render_checkout(
        self,
        request: HttpRequest,
        request_type: str,
        transaction_uuid: str,
        extra_config: dict | None = None,
    ) -> HttpResponse:
        """Build checkout page with capture context JWT."""
        target_origin = request.build_absolute_uri('/').rstrip('/')
        
        capture_context = self.generate_capture_context([target_origin])
        
        # Build callback URL using reverse()
        callback_path = reverse('payment_callback', kwargs={'provider_name': 'cybersource_rest'})
        callback_url = f"{target_origin}{callback_path}"
        
        client_config = {
            'capture_context': capture_context,
            'request_type': request_type,
            'transaction_uuid': str(transaction_uuid),
            'callback_url': callback_url,
        }
        
        if extra_config:
            client_config.update(extra_config)
        
        return render(request, 'flex_microform.html', {
            'client_config': client_config,
        })
    
    def checkout_subscribe(self, request: HttpRequest, s_request: Any) -> HttpResponse:
        """Handle Flex Microform subscription checkout."""
        return self._render_checkout(
            request=request,
            request_type='subscribe',
            transaction_uuid=s_request.transaction_uuid,
            extra_config={
                'reference_number': s_request.reference_number,
                'amount': str(s_request.amount),
                'recurring_amount': str(s_request.recurring_amount),
                'recurring_frequency': s_request.recurring_frequency,
                'recurring_start_date': s_request.get_formatted_start_date(),
            },
        )
    
    def checkout_purchase(self, request: HttpRequest, p_request: Any) -> HttpResponse:
        """Handle Flex Microform purchase checkout."""
        return self._render_checkout(
            request=request,
            request_type='purchase',
            transaction_uuid=p_request.transaction_uuid,
            extra_config={
                'reference_number': p_request.reference_number,
                'amount': str(p_request.amount),
            },
        )
    
    def checkout_change(self, request: HttpRequest, c_request: Any) -> HttpResponse:
        """Handle Flex Microform subscription change checkout."""
        return self._render_checkout(
            request=request,
            request_type='change',
            transaction_uuid=c_request.transaction_uuid,
            extra_config={
                'amount': str(c_request.amount),
                'recurring_amount': str(c_request.recurring_amount),
            },
        )
    
    def checkout_update(self, request: HttpRequest, u_request: Any) -> HttpResponse:
        """Handle Flex Microform payment info update checkout."""
        return self._render_checkout(
            request=request,
            request_type='update',
            transaction_uuid=u_request.transaction_uuid,
        )
    
    def handle_webhook(self, request: HttpRequest) -> str | HttpResponse:
        """
        Validate Flex Microform callback and extract data.
        """
        ### validation ###
        data = request.POST
        transient_token = data.get('transient_token')
        if not transient_token:
            raise CallbackValidationError("No transient_token in request")

        # parsing ensures that the response is signed by fetching a public key from Cybersource's servers.
        # we don't actually care about the value, because we're about to convert to a customer token.
        try:
            _ = parse_capture_context_response(transient_token, self.microform_api.api_client.mconfig)
        except Exception as e:
            # may raise ValueError, Exception (if can't reach server for key), or Jwt errors
            trace.log(
                title='Token Validation Failed',
                lane='Server',
                data={'error': str(e)},
            )
            raise CallbackValidationError(f"Invalid transient_token: {e}") from e
        
        trace.log(
            title='Token Signature Valid',
            lane='Server',
            data={'transient_token': transient_token[:50] + '...'},
        )

        ### processing ###

        outgoing_transaction = self.get_outgoing_transaction(data.get('transaction_uuid'))
        trace.db(outgoing_transaction, title='OutgoingTransaction', action='Fetch')
        request_type = data.get('request_type')

        # Create customer token
        reference_code = outgoing_transaction.reference_number
        token_result = self.create_customer_token(
            transient_token=transient_token,
            reference_code=reference_code,
        )

        provider_data = {
            'customer_id': token_result.customer_id,
            'payment_instrument_id': token_result.payment_instrument_id,
            'reference_number': reference_code,
        }

        # If this is a subscription, create it
        if request_type == 'subscribe':
            # Convert frequency to billing period
            frequency = getattr(outgoing_transaction, 'recurring_frequency', 'monthly')
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
            start_date = getattr(outgoing_transaction, 'recurring_start_date', date.today())
            if hasattr(start_date, 'strftime'):
                start_date_str = start_date.strftime('%Y-%m-%d')
            else:
                start_date_str = str(start_date)

            subscription_result = self.create_subscription(
                customer_token_id=token_result.customer_id,
                reference_code=reference_code,
                subscription_name=f"{outgoing_transaction.customer_type}-{outgoing_transaction.customer_pk}",
                start_date=start_date_str,
                billing_amount=str(outgoing_transaction.recurring_amount),
                billing_period_unit=billing_period_unit,
                billing_period_length=billing_period_length,
            )

            provider_data['subscription_id'] = subscription_result.subscription_id

        # Save response and update related models
        Response.save_callback_response(
            outgoing_transaction,
            decision='ACCEPT',
            message='Transaction successful',
            raw_response={
                'token_result': {
                    'customer_id': token_result.customer_id,
                    'payment_instrument_id': token_result.payment_instrument_id,
                    'status': token_result.status,
                },
                'subscription_id': provider_data.get('subscription_id'),
            },
            provider_data=provider_data,
        )
        
        # Log the final DB state (subscription-related transactions only)
        if hasattr(outgoing_transaction, 'subscription_agreement'):
            outgoing_transaction.subscription_agreement.refresh_from_db()
            trace.db(outgoing_transaction.subscription_agreement, title='SubscriptionAgreement (status updated)')
        
        # Redirect user back to Perma.cc
        return self.get_success_redirect()
    
    def has_credentials(self) -> bool:
        """Check if credentials are configured."""
        return all([
            self.merchant_id,
            self.key_id,
            self.shared_secret,
        ])
    
    def probe_credentials(self) -> bool:
        """
        Probe the CyberSource REST API to verify credentials work.
        
        Makes a lightweight API call (generate capture context) to verify
        the credentials are valid and the service is available.
        """
        try:
            # Generate a capture context with a dummy origin - this validates
            # credentials without any side effects
            self.generate_capture_context(['https://probe.example.com'])
            return True
        except Exception as e:
            logger.warning("CyberSource REST credential probe failed: %s", e)
            return False
