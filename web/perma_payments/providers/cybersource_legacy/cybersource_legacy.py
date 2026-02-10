"""
CyberSource Legacy (Secure Acceptance Web/Mobile) payment provider.

This provider implements the redirect-based CyberSource Secure Acceptance
payment flow, where users are redirected to CyberSource's hosted payment page.
"""

import logging
from collections import OrderedDict

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.debug import sensitive_variables

from .constants import CS_PAYMENT_URL, CS_TOKEN_UPDATE_URL, CS_SUBSCRIPTION_SEARCH_URL
from ..base import (
    PaymentProvider,
    CallbackValidationError,
)
from perma_payments.models import SubscriptionRequest, PurchaseRequest, ChangeRequest, UpdateRequest, Response
from perma_payments.security import InvalidTransmissionException, sign_data, \
    stringify_for_signature, is_valid_signature, retrieve_fields
from perma_payments.tests import trace

logger = logging.getLogger(__name__)


# Fields required from CyberSource callback
CALLBACK_FIELDS = [
    'req_transaction_uuid',
    'decision',
    'reason_code',
    'message',
]


@sensitive_variables()
def prep_for_cybersource(signed_fields, unsigned_fields={}, secret_key=None):
    """
    Takes a dict of fields to sign, and optionally a dict of fields not to sign.
    Creates the appropriate signature, adds some required administrative fields,
    and packages everything up, returning a dict of data to POST to CyberSource
    via form inputs. (e.g. <input type="hidden" name="KEY" value="VALUE"> for KEY,VALUE in returned_dict)

    Note: if additional fields are POSTed, or if any of these fields fail to be POSTed,
    CyberSource will reject the communication's signature and return 403 Forbidden.

    Args:
        signed_fields: Dict of fields to sign
        unsigned_fields: Dict of fields not to sign
        secret_key: Secret key for signing. If not provided, uses provider config.
    """
    signed_fields = dict(
        signed_fields,
        unsigned_field_names=','.join(sorted(unsigned_fields)),
        signed_field_names=','.join(sorted(list(signed_fields) + ['signed_field_names', 'unsigned_field_names']))
    )
    to_post = {}
    to_post.update(signed_fields)
    to_post.update(unsigned_fields)
    to_post['signature'] = sign_data(stringify_for_signature(signed_fields), secret_key).decode('utf-8')
    return to_post


@sensitive_variables()
def process_cybersource_transmission(transmitted_data, fields):
    # Transmitted data must include signature, signed_field_names,
    # and all fields listed in signed_field_names
    try:
        signature = transmitted_data['signature']
        signed_field_names = transmitted_data['signed_field_names']
        signed_fields = OrderedDict()
        for field in signed_field_names.split(','):
            signed_fields[field] = transmitted_data[field]
    except KeyError as e:
        msg = 'Incomplete POST to CyberSource callback route: missing {}'.format(e)
        logger.warning(msg)
        raise InvalidTransmissionException(msg)

    # The signature must be valid
    if not is_valid_signature(signed_fields, signature):
        msg = 'Data with invalid signature POSTed to CyberSource callback route'
        logger.warning(msg)
        raise InvalidTransmissionException(msg)

    # Great! Return the subset of fields we want
    return retrieve_fields(transmitted_data, fields)


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
    manual_cancellation_url = CS_SUBSCRIPTION_SEARCH_URL[settings.PROVIDER_ENVIRONMENT]
    
    def __init__(self, config: dict):
        super().__init__(config)

        # Credentials from provider config
        self.access_key = config.get('access_key', '')
        self.profile_id = config.get('profile_id', '')
        self.secret_key = config.get('secret_key', '')
    
    def _render_checkout(
        self,
        request: HttpRequest,
        post_url: str,
        extra_fields: dict,
    ) -> HttpResponse:
        """Render checkout page with signed fields for CyberSource redirect."""
        signed_fields = {
            'access_key': self.access_key,
            'profile_id': self.profile_id,
            **extra_fields,
        }
        
        return render(request, 'redirect.html', {
            'post_to_url': post_url,
            'fields_to_post': prep_for_cybersource(signed_fields, secret_key=self.secret_key),
        })
    
    def checkout_subscribe(self, request: HttpRequest, s_request: SubscriptionRequest) -> HttpResponse:
        """Handle new subscription checkout."""
        return self._render_checkout(
            request=request,
            post_url=CS_PAYMENT_URL[settings.PROVIDER_ENVIRONMENT],
            extra_fields={
                'amount': s_request.amount,
                'currency': s_request.currency,
                'locale': s_request.locale,
                'payment_method': s_request.payment_method,
                'recurring_amount': s_request.recurring_amount,
                'recurring_frequency': s_request.recurring_frequency,
                'recurring_start_date': s_request.get_formatted_start_date(),
                'reference_number': s_request.reference_number,
                'signed_date_time': s_request.get_formatted_datetime(),
                'transaction_type': s_request.transaction_type,
                'transaction_uuid': s_request.transaction_uuid,
            },
        )
    
    def checkout_purchase(self, request: HttpRequest, p_request: PurchaseRequest) -> HttpResponse:
        """Handle one-time purchase checkout."""
        return self._render_checkout(
            request=request,
            post_url=CS_PAYMENT_URL[settings.PROVIDER_ENVIRONMENT],
            extra_fields={
                'amount': p_request.amount,
                'currency': p_request.currency,
                'locale': p_request.locale,
                'payment_method': p_request.payment_method,
                'reference_number': p_request.reference_number,
                'signed_date_time': p_request.get_formatted_datetime(),
                'transaction_type': p_request.transaction_type,
                'transaction_uuid': p_request.transaction_uuid,
            },
        )
    
    def checkout_change(self, request: HttpRequest, c_request: ChangeRequest) -> HttpResponse:
        """Handle subscription change checkout."""
        sub_request = c_request.subscription_agreement.subscription_request
        sub_response = sub_request.subscription_request_response
        
        return self._render_checkout(
            request=request,
            post_url=CS_TOKEN_UPDATE_URL[settings.PROVIDER_ENVIRONMENT],
            extra_fields={
                'amount': c_request.amount,
                'currency': c_request.currency,
                'locale': c_request.locale,
                'payment_method': c_request.payment_method,
                'payment_token': sub_response.payment_token,
                'recurring_amount': c_request.recurring_amount,
                'reference_number': c_request.reference_number,
                'signed_date_time': c_request.get_formatted_datetime(),
                'transaction_type': c_request.transaction_type,
                'transaction_uuid': c_request.transaction_uuid,
            },
        )
    
    def checkout_update(self, request: HttpRequest, u_request: UpdateRequest) -> HttpResponse:
        """Handle payment info update checkout."""
        sa = u_request.subscription_agreement
        s_request = sa.subscription_request
        s_response = s_request.subscription_request_response
        
        return self._render_checkout(
            request=request,
            post_url=CS_TOKEN_UPDATE_URL[settings.PROVIDER_ENVIRONMENT],
            extra_fields={
                'allow_payment_token_update': 'true',
                'locale': s_request.locale,
                'payment_method': s_request.payment_method,
                'payment_token': s_response.payment_token,
                'reference_number': u_request.reference_number,
                'signed_date_time': u_request.get_formatted_datetime(),
                'transaction_type': u_request.transaction_type,
                'transaction_uuid': u_request.transaction_uuid,
            },
        )
    
    def handle_webhook(self, request: HttpRequest) -> str:
        """
        Validate CyberSource callback and extract data.
        
        Verifies the signature on the POST data and extracts the transaction UUID.
        
        Note: CyberSource Legacy callbacks are configured in the CyberSource Business
        Center to redirect users back to Perma.cc. This endpoint just records the
        transaction result. The "OK" response is shown briefly before the Business
        Center redirect takes effect.
        """
        ### validation ###

        # Determine which fields to require based on what's in the POST
        fields = list(CALLBACK_FIELDS)
        if 'payment_token' in request.POST:
            fields.append('payment_token')
        
        try:
            data = process_cybersource_transmission(request.POST, fields)
        except InvalidTransmissionException as e:
            trace.log(
                title='Signature Validation Failed',
                lane='Server',
                data={'error': str(e)},
            )
            raise CallbackValidationError(str(e))
        
        trace.log(
            title='Callback Signature Valid',
            lane='Server',
            data={
                'decision': data.get('decision'),
                'message': data.get('message'),
                'reason_code': data.get('reason_code'),
            },
        )

        ### processing ###

        outgoing_transaction = self.get_outgoing_transaction(data.get('req_transaction_uuid'))
        trace.db(outgoing_transaction, title='OutgoingTransaction', action='Fetch')

        # Build provider_data based on what was returned
        provider_data = {
            'reason_code': data['reason_code'],  # CyberSource-specific reason code
        }
        if 'payment_token' in data:
            payment_token = data['payment_token']
            # Validate payment token format (should not be 16-digit format-preserving)
            if len(payment_token) == 16 and payment_token.isdigit():
                logger.error(
                    "Received 16-digit format-preserving payment token. "
                    "Perma-Payments does not support this format."
                )
            provider_data['payment_token'] = payment_token

        # Save response and update SubscriptionAgreement
        Response.save_callback_response(
            outgoing_transaction,
            decision=data['decision'],
            message=data['message'],
            raw_response=dict(request.POST),
            provider_data=provider_data,
        )
        
        # Log the final DB state
        if hasattr(outgoing_transaction, 'subscription_agreement'):
            outgoing_transaction.subscription_agreement.refresh_from_db()
            trace.db(outgoing_transaction.subscription_agreement, title='SubscriptionAgreement (status updated)')

        return "OK"
    
    def has_credentials(self) -> bool:
        """Check if credentials are configured."""
        return all([
            self.access_key,
            self.profile_id,
            self.secret_key,
        ])
    
    # Note: probe_credentials() is not overridden because CyberSource Legacy
    # uses redirect-based flow with no API endpoint to probe. The default
    # implementation (return True) is appropriate here.

