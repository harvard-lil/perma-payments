import csv
from datetime import datetime
from pytz import timezone
from functools import wraps
import io

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, ObjectDoesNotExist, MultipleObjectsReturned, PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.timezone import make_aware
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .constants import (
    CS_PAYMENT_URL,
    CS_SUBSCRIPTION_SEARCH_URL,
    CS_TOKEN_UPDATE_URL
)
from .custom_errors import bad_request
from .email import send_self_email
from .models import (
    SubscriptionAgreement,
    OutgoingTransaction,
    SubscriptionRequest,
    ChangeRequest,
    UpdateRequest,
    PurchaseRequest,
    Response,
    SubscriptionRequestResponse,
    ChangeRequestResponse,
    UpdateRequestResponse,
    PurchaseRequestResponse
)
from .providers import get_provider, get_checkout_provider
from .providers.base import CallbackValidationError, NoProviderAvailable
from .security import (
   InvalidTransmissionException,
   process_cybersource_transmission,
   prep_for_perma,
   process_perma_transmission,
   encrypt_for_storage,
   stringify_data,
)

import logging
logger = logging.getLogger(__name__)

#
# UTILS
#

FIELDS_REQUIRED_FROM_PERMA = {
    'purchase': [
        'customer_pk',
        'customer_type',
        'amount',
        'link_quantity'
    ],
    'acknowledge_purchase': [
        'purchase_pk'
    ],
    'subscribe': [
        'customer_pk',
        'customer_type',
        'amount',
        'recurring_amount',
        'recurring_frequency',
        'recurring_start_date',
        'link_limit',
        'link_limit_effective_timestamp'
    ],
    'change': [
        'customer_pk',
        'customer_type',
        'amount',
        'recurring_amount',
        'link_limit',
        'link_limit_effective_timestamp'
    ],
    'update': [
        'customer_pk',
        'customer_type'
    ],
    'subscription': [
        'customer_pk',
        'customer_type'
    ],
    'cancel_request': [
        'customer_pk',
        'customer_type'
    ]
}

FIELDS_REQUIRED_FOR_CYBERSOURCE = {
    'purchase': [
        'access_key',
        'amount',
        'currency',
        'locale',
        'payment_method',
        'profile_id',
        'reference_number',
        'signed_date_time',
        'transaction_type',
        'transaction_uuid'
    ],
    'subscribe': [
        'access_key',
        'amount',
        'currency',
        'locale',
        'payment_method',
        'profile_id',
        'recurring_amount',
        'recurring_frequency',
        'recurring_start_date',
        'reference_number',
        'signed_date_time',
        'transaction_type',
        'transaction_uuid'
    ],
    'change': [
        'access_key',
        'allow_payment_token_update',
        'amount',
        'currency',
        'locale',
        'payment_method',
        'payment_token',
        'profile_id',
        'recurring_amount',
        'reference_number',
        'signed_date_time',
        'transaction_type',
        'transaction_uuid'
    ],
    'update': [
        'access_key',
        'allow_payment_token_update',
        'locale',
        'payment_method',
        'payment_token',
        'profile_id',
        'reference_number',
        'signed_date_time',
        'transaction_type',
        'transaction_uuid'
    ]
}

FIELDS_REQUIRED_FROM_CYBERSOURCE = {
    'cybersource_callback': [
        'req_transaction_uuid',
        'decision',
        'reason_code',
        'message'
    ]
}

SENSITIVE_POST_PARAMETERS = [
    'payment_token',
    'req_access_key',
    'req_bill_to_address_city',
    'req_bill_to_address_country',
    'req_bill_to_address_line1',
    'req_bill_to_address_postal_code',
    'req_bill_to_address_state',
    'req_bill_to_email',
    'req_bill_to_forename',
    'req_bill_to_surname',
    'req_card_expiry_date',
    'req_card_number',
    'req_payment_token',
    'req_profile_id',
    'signature'
]


def redact(post):
    return {k: v for (k, v) in post.items() if k not in SENSITIVE_POST_PARAMETERS}


def skip_lines(csv_file, lines):
    """
    Given a file object, advances the read/write head <lines> number of lines.
    Useful for skipping over undesired lines of a file before processing.
    Returns None.
    """
    for i in range(lines):
        csv_file.readline()


def in_mem_csv_to_dict_reader(csv_file):
    """
    A POSTed file is processed by Django and made available as an InMemoryUploadedFile.
    InMemoryUploadedFiles lack the necessary methods to pass them to a csv reader in the normal way.
    This is a work around.
    https://docs.djangoproject.com/en/1.11/ref/files/uploads/
    """
    return csv.DictReader(io.StringIO(csv_file.read().decode('utf-8')))


def user_passes_test_or_403(test_func):
    """
    Decorator for views that checks that the user passes the given test,
    raising PermissionDenied if not. Based on Django's user_passes_test.
    The test should be a callable that takes the user object and
    returns True if the user passes.
    """
    def decorator(view_func):
        @login_required()
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not test_func(request.user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def formatted_date_or_none(dt):
    if dt:
        return datetime.strftime(dt, '%Y-%m-%dT%H:%M:%S.%fZ')
    return None


#
# VIEWS
#

@require_http_methods(["GET"])
def index(request):
    return render(request, 'generic.html', {'heading': "Perma Payments",
                                            'message': "A window to CyberSource Secure Acceptance Web/Mobile"})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters('encrypted_data')
def purchase(request):
    """
    Processes user-initiated one-time purchase requests from Perma.cc;
    Redirects user to payment provider for payment.
    """
    if request.method == "GET":
        return render(request, 'generic.html', {
            'heading': "Perma Payments",
            'message': "Payment processing service for Perma.cc"
        })

    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['purchase'])
    except InvalidTransmissionException:
        return bad_request(request)

    # Get the appropriate payment provider
    try:
        provider = get_checkout_provider(data['customer_pk'], data['customer_type'])
    except NoProviderAvailable:
        logger.error("No payment provider available for purchase request")
        return render(request, 'generic.html', {
            'heading': "Service Unavailable",
            'message': "Payment processing is temporarily unavailable. Please try again later."
        })

    # The purchase request fields must each be valid.
    try:
        with transaction.atomic():
            p_request = PurchaseRequest(
                customer_pk=data['customer_pk'],
                customer_type=data['customer_type'],
                amount=data['amount'],
                link_quantity=data['link_quantity'],
                payment_provider=provider.name,
            )
            p_request.full_clean()
            p_request.save()
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc purchase form: {}'.format(e))
        return bad_request(request)

    # Get checkout context from the provider
    return_url = request.build_absolute_uri('/')
    checkout_context = provider.get_checkout_context(
        request_type='purchase',
        request_data=data,
        outgoing_transaction=p_request,
        return_url=return_url,
    )

    # Build template context
    context = {
        'post_to_url': checkout_context.post_url,
        'fields_to_post': checkout_context.fields_to_post,
        'client_config': checkout_context.client_config,
    }
    context.update(checkout_context.extra_context)

    logger.info("Purchase request received for {} {} (provider: {})".format(
        data['customer_type'], data['customer_pk'], provider.name
    ))
    return render(request, checkout_context.template, context)


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def acknowledge_purchase(request):
    """
    Records that Perma has acknowledged a purchase.
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['acknowledge_purchase'])
    except InvalidTransmissionException:
        return bad_request(request)

    with transaction.atomic():
        try:
            purchase = PurchaseRequestResponse.objects.select_for_update().get(pk=data['purchase_pk'])
        except PurchaseRequestResponse.DoesNotExist:
            logger.warning('Perma attempted to acknowledge non-existent purchase {}'.format(data['purchase_pk']))
            return bad_request(request)

        if not purchase.inform_perma:
            logger.warning('Perma attempted to acknowledge unacknowledgeable purchase {}'.format(data['purchase_pk']))
            return bad_request(request)
        if purchase.perma_acknowledged_at:
            logger.warning('Perma attempted to acknowledge already-acknowledged purchase {}'.format(data['purchase_pk']))
            return bad_request(request)

        purchase.perma_acknowledged_at = datetime.now(tz=timezone(settings.TIME_ZONE))
        purchase.save(update_fields=['perma_acknowledged_at'])
        logger.info("Purchase {} acknowledged by Perma".format(data['purchase_pk']))
        return JsonResponse({'status': 'ok'})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters('encrypted_data')
def subscribe(request):
    """
    Processes user-initiated subscription requests from Perma.cc;
    Redirects user to payment provider for payment.
    """
    if request.method == "GET":
        return render(request, 'generic.html', {
            'heading': "Perma Payments",
            'message': "Payment processing service for Perma.cc"
        })
    
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['subscribe'])
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must not already have a standing subscription.
    if SubscriptionAgreement.customer_standing_subscription(data['customer_pk'], data['customer_type']):
        return render(request, 'generic.html', {'heading': "Good News!",
                                                'message': "You already have a subscription to Perma.cc.<br>" +
                                                           "If you believe you have reached this page in error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})

    # Get the appropriate payment provider
    try:
        provider = get_checkout_provider(data['customer_pk'], data['customer_type'])
    except NoProviderAvailable:
        logger.error("No payment provider available for subscribe request")
        return render(request, 'generic.html', {
            'heading': "Service Unavailable",
            'message': "Payment processing is temporarily unavailable. Please try again later."
        })

    # The subscription request fields must each be valid.
    try:
        with transaction.atomic():
            s_agreement = SubscriptionAgreement(
                customer_pk=data['customer_pk'],
                customer_type=data['customer_type'],
                status='Pending',
                payment_provider=provider.name,
            )
            s_agreement.full_clean()
            s_agreement.save()
            s_request = SubscriptionRequest(
                subscription_agreement=s_agreement,
                amount=data['amount'],
                recurring_amount=data['recurring_amount'],
                recurring_frequency=data['recurring_frequency'],
                recurring_start_date=data['recurring_start_date'],
                link_limit=data['link_limit'],
                link_limit_effective_timestamp=make_aware(datetime.fromtimestamp(data['link_limit_effective_timestamp']))
            )
            s_request.full_clean()
            s_request.save()
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc subscribe form: {}'.format(e))
        return bad_request(request)

    # Get checkout context from the provider
    return_url = request.build_absolute_uri('/')
    checkout_context = provider.get_checkout_context(
        request_type='subscribe',
        request_data=data,
        outgoing_transaction=s_request,
        return_url=return_url,
    )

    # Build template context
    context = {
        'post_to_url': checkout_context.post_url,
        'fields_to_post': checkout_context.fields_to_post,
        'client_config': checkout_context.client_config,
    }
    context.update(checkout_context.extra_context)

    logger.info("Subscription request received for {} {} (provider: {})".format(
        data['customer_type'], data['customer_pk'], provider.name
    ))
    return render(request, checkout_context.template, context)


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def change(request):
    """
    Processes user-initiated requests from Perma.cc;
    Redirects user to payment provider for payment.
    Updates charge amount and frequency.
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['change'])
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must have a subscription that can be updated.
    sa = SubscriptionAgreement.customer_standing_subscription(data['customer_pk'], data['customer_type'])
    if not sa or not sa.can_be_altered():
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})

    # Get the provider for this subscription
    provider = get_provider(sa.payment_provider)

    # The change request fields must each be valid.
    try:
        c_request = ChangeRequest(
            subscription_agreement=sa,
            amount=data['amount'],
            recurring_amount=data['recurring_amount'],
            link_limit=data['link_limit'],
            link_limit_effective_timestamp=make_aware(datetime.fromtimestamp(data['link_limit_effective_timestamp']))
        )
        c_request.full_clean()
        c_request.save()
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc change form: {}'.format(e))
        return bad_request(request)

    # Get checkout context from the provider
    return_url = request.build_absolute_uri('/')
    checkout_context = provider.get_checkout_context(
        request_type='change',
        request_data=data,
        outgoing_transaction=c_request,
        return_url=return_url,
    )

    # Build template context
    context = {
        'post_to_url': checkout_context.post_url,
        'fields_to_post': checkout_context.fields_to_post,
        'client_config': checkout_context.client_config,
    }
    context.update(checkout_context.extra_context)

    logger.info("Change request received for {} {} (provider: {})".format(
        data['customer_type'], data['customer_pk'], provider.name
    ))
    return render(request, checkout_context.template, context)


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def update(request):
    """
    Processes user-initiated requests from Perma.cc;
    Redirects user to payment provider.
    Updates payment information.
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['update'])
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must have a subscription that can be updated.
    sa = SubscriptionAgreement.customer_standing_subscription(data['customer_pk'], data['customer_type'])
    if not sa or not sa.can_be_altered():
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Update Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})

    # Get the provider for this subscription
    provider = get_provider(sa.payment_provider)

    # The update request fields must each be valid.
    try:
        u_request = UpdateRequest(
            subscription_agreement=sa,
        )
        u_request.full_clean()
        u_request.save()
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc update form: {}'.format(e))
        return bad_request(request)

    # Get checkout context from the provider
    return_url = request.build_absolute_uri('/')
    checkout_context = provider.get_checkout_context(
        request_type='update',
        request_data=data,
        outgoing_transaction=u_request,
        return_url=return_url,
    )

    # Build template context
    context = {
        'post_to_url': checkout_context.post_url,
        'fields_to_post': checkout_context.fields_to_post,
        'client_config': checkout_context.client_config,
    }
    context.update(checkout_context.extra_context)

    logger.info("Update payment information request received for {} {} (provider: {})".format(
        data['customer_type'], data['customer_pk'], provider.name
    ))
    return render(request, checkout_context.template, context)


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters(*SENSITIVE_POST_PARAMETERS)
def cybersource_callback(request):
    """
    In dev, curl http://your-docker-machine-ip/cybersource-callback/ -X POST -d 'path/to/sample_response.txt'
    """
    try:
        data = process_cybersource_transmission(request.POST, FIELDS_REQUIRED_FROM_CYBERSOURCE['cybersource_callback'])
    except InvalidTransmissionException:
        return bad_request(request)

    related_request = OutgoingTransaction.objects.get(transaction_uuid=data['req_transaction_uuid'])
    decision = data['decision']
    reason_code = data['reason_code']
    message = data['message']

    if isinstance(related_request, UpdateRequest):
        Response.save_new_with_encrypted_full_response(
            UpdateRequestResponse,
            request.POST,
            {
                'related_request': related_request,
                'decision': decision,
                'reason_code': reason_code,
                'message': message,
            }
        )

    elif isinstance(related_request, ChangeRequest):
        Response.save_new_with_encrypted_full_response(
            ChangeRequestResponse,
            request.POST,
            {
                'related_request': related_request,
                'decision': decision,
                'reason_code': reason_code,
                'message': message,
            }
        )
        related_request.subscription_agreement.update_after_cs_decision(related_request, decision, redact(request.POST))

    elif isinstance(related_request, SubscriptionRequest):
        payment_token = request.POST.get('payment_token', '')

        # Perma-Payments does not support 16-digit format-preserving Payment Tokens.
        # See docstring for SubscriptionAgreement model for details.
        if len(payment_token) == 16:
            logger.error("16-digit Payment Token received in response to subscription request {}. Not supported by Perma-Payments! Investigate ASAP.".format(related_request.pk))

        Response.save_new_with_encrypted_full_response(
            SubscriptionRequestResponse,
            request.POST,
            {
                'related_request': related_request,
                'decision': decision,
                'reason_code': reason_code,
                'message': message,
                'payment_token': payment_token,
            }
        )
        
        # Also save payment_token to provider_data on SubscriptionAgreement
        sa = related_request.subscription_agreement
        if payment_token and decision in ('ACCEPT', 'REVIEW'):
            sa.provider_data = {'payment_token': payment_token}
            sa.save(update_fields=['provider_data'])
        
        sa.update_after_cs_decision(related_request, decision, redact(request.POST))

    elif isinstance(related_request, PurchaseRequest):
        response = Response.save_new_with_encrypted_full_response(
            PurchaseRequestResponse,
            request.POST,
            {
                'related_request': related_request,
                'decision': decision,
                'reason_code': reason_code,
                'message': message,
            }
        )
        response.act_on_cs_decision(redact(request.POST))

    else:
        raise NotImplementedError("Can't handle a response of type {}, returned in response to outgoing transaction {}".format(type(related_request), related_request.pk))

    return render(request, 'generic.html', {'heading': 'CyberSource Callback', 'message': 'OK'})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def payment_callback(request, provider_name):
    """
    Generic callback endpoint for payment providers.
    
    Routes to the appropriate provider based on the URL parameter.
    URL pattern: /callback/<provider_name>/
    """
    try:
        provider = get_provider(provider_name)
    except Exception as e:
        logger.error("Unknown payment provider in callback: %s", provider_name)
        return bad_request(request)
    
    try:
        result = provider.process_callback(request)
    except CallbackValidationError as e:
        logger.warning("Callback validation failed for %s: %s", provider_name, e)
        return bad_request(request)
    
    # Find the related request if we have a transaction_uuid
    transaction_uuid = request.POST.get('transaction_uuid') or request.GET.get('transaction_uuid')
    if transaction_uuid:
        try:
            related_request = OutgoingTransaction.objects.get(transaction_uuid=transaction_uuid)
            
            # Process based on request type
            if isinstance(related_request, SubscriptionRequest):
                # Save response
                Response.save_new_with_encrypted_full_response(
                    SubscriptionRequestResponse,
                    result.raw_response,
                    {
                        'related_request': related_request,
                        'decision': result.decision,
                        'reason_code': result.reason_code,
                        'message': result.message,
                        'payment_token': result.provider_data.get('payment_token', ''),
                    }
                )
                
                # Update SubscriptionAgreement with provider data
                sa = related_request.subscription_agreement
                if result.success and result.provider_data:
                    sa.provider_data = result.provider_data
                    sa.save(update_fields=['provider_data'])
                
                sa.update_after_cs_decision(related_request, result.decision, result.raw_response)
                
            elif isinstance(related_request, PurchaseRequest):
                response = Response.save_new_with_encrypted_full_response(
                    PurchaseRequestResponse,
                    result.raw_response,
                    {
                        'related_request': related_request,
                        'decision': result.decision,
                        'reason_code': result.reason_code,
                        'message': result.message,
                    }
                )
                response.act_on_cs_decision(result.raw_response)
                
            elif isinstance(related_request, ChangeRequest):
                Response.save_new_with_encrypted_full_response(
                    ChangeRequestResponse,
                    result.raw_response,
                    {
                        'related_request': related_request,
                        'decision': result.decision,
                        'reason_code': result.reason_code,
                        'message': result.message,
                    }
                )
                related_request.subscription_agreement.update_after_cs_decision(
                    related_request, result.decision, result.raw_response
                )
                
            elif isinstance(related_request, UpdateRequest):
                Response.save_new_with_encrypted_full_response(
                    UpdateRequestResponse,
                    result.raw_response,
                    {
                        'related_request': related_request,
                        'decision': result.decision,
                        'reason_code': result.reason_code,
                        'message': result.message,
                    }
                )
                
        except OutgoingTransaction.DoesNotExist:
            logger.warning("No transaction found for UUID: %s", transaction_uuid)
    
    return render(request, 'generic.html', {
        'heading': f'{provider_name.title()} Callback',
        'message': 'OK' if result.success else f'Error: {result.message}'
    })


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    """
    Stripe webhook endpoint for asynchronous events.
    
    Handles events like invoice.paid, customer.subscription.deleted, etc.
    """
    try:
        provider = get_provider('stripe')
    except Exception as e:
        logger.error("Stripe provider not configured: %s", e)
        return JsonResponse({'error': 'Stripe not configured'}, status=500)
    
    try:
        result = provider.process_webhook(request)
    except CallbackValidationError as e:
        logger.warning("Stripe webhook validation failed: %s", e)
        return JsonResponse({'error': str(e)}, status=400)
    
    # Handle specific webhook events that need to update subscriptions
    if result.reason_code == 'SUBSCRIPTION_DELETED':
        # Find and update the subscription
        subscription_id = result.provider_data.get('subscription_id')
        if subscription_id:
            try:
                sa = SubscriptionAgreement.objects.get(
                    provider_data__subscription_id=subscription_id,
                    payment_provider='stripe'
                )
                sa.status = 'Canceled'
                sa.save(update_fields=['status'])
                logger.info("Stripe subscription %s marked as Canceled", subscription_id)
            except SubscriptionAgreement.DoesNotExist:
                logger.warning("No subscription found for Stripe ID: %s", subscription_id)
    
    elif result.reason_code == 'PAYMENT_FAILED':
        subscription_id = result.provider_data.get('subscription_id')
        if subscription_id:
            try:
                sa = SubscriptionAgreement.objects.get(
                    provider_data__subscription_id=subscription_id,
                    payment_provider='stripe'
                )
                sa.status = 'Hold'
                sa.save(update_fields=['status'])
                logger.info("Stripe subscription %s marked as Hold due to payment failure", subscription_id)
            except SubscriptionAgreement.DoesNotExist:
                logger.warning("No subscription found for Stripe ID: %s", subscription_id)
    
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def subscription(request):
    """
    Returns a simplified version of a customer's subscription status,
    as needed for making decisions in Perma.
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['subscription'])
    except InvalidTransmissionException:
        return bad_request(request)

    standing_subscription = SubscriptionAgreement.customer_standing_subscription(data['customer_pk'], data['customer_type'])
    if not standing_subscription:
        subscription = None
    else:
        subscription = {
            'link_limit': standing_subscription.current_link_limit,
            'link_limit_effective_timestamp': formatted_date_or_none(standing_subscription.current_link_limit_effective_timestamp),
            'rate': standing_subscription.current_rate,
            'frequency': standing_subscription.current_frequency,
            'paid_through': formatted_date_or_none(standing_subscription.paid_through),
            'reference_number': standing_subscription.subscription_request.reference_number
        }

        if standing_subscription.cancellation_requested and standing_subscription.status != 'Canceled':
            subscription['status'] = 'Cancellation Requested'
        else:
            subscription['status'] = standing_subscription.status

    # Mention any bonus links that have been purchased, but not yet acknowledged
    purchases = PurchaseRequestResponse.customer_unacknowledged(data['customer_pk'], data['customer_type'])

    response = {
        'customer_pk': data['customer_pk'],
        'customer_type': data['customer_type'],
        'subscription': subscription,
        'timestamp': datetime.utcnow().timestamp(),
        'purchases': purchases
    }
    return JsonResponse({'encrypted_data': prep_for_perma(response).decode('ascii')})


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def purchase_history(request):
    """
    Returns a customer's one-time purchase history.
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['subscription'])
    except InvalidTransmissionException:
        return bad_request(request)

    purchase_history = PurchaseRequestResponse.customer_history(data['customer_pk'], data['customer_type'])

    response = {
        'customer_pk': data['customer_pk'],
        'customer_type': data['customer_type'],
        'purchase_history': purchase_history,
        'timestamp': datetime.utcnow().timestamp()
    }
    return JsonResponse({'encrypted_data': prep_for_perma(response).decode('ascii')})


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def cancel_request(request):
    """
    Records a cancellation request from Perma.cc
    """
    try:
        data = process_perma_transmission(request.POST, FIELDS_REQUIRED_FROM_PERMA['cancel_request'])
    except InvalidTransmissionException:
        return bad_request(request)

    # The user must have a subscription that can be canceled.
    sa = SubscriptionAgreement.customer_standing_subscription(data['customer_pk'], data['customer_type'])
    if not sa or not sa.can_be_altered():
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Cancellation Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})

    context = {
        'customer_pk': data['customer_pk'],
        'customer_type': data['customer_type'],
        'search_url': CS_SUBSCRIPTION_SEARCH_URL[settings.CS_MODE],
        'perma_url': settings.PERMA_URL,
        'individual_detail_path': settings.INDIVIDUAL_DETAIL_PATH,
        'registrar_detail_path': settings.REGISTRAR_DETAIL_PATH,
        'registrar_users_path': settings.REGISTRAR_USERS_PATH,
        'merchant_reference_number': sa.subscription_request.reference_number
    }
    logger.info("Cancellation request received from {} {} for {}".format(data['customer_pk'], data['customer_type'], context['merchant_reference_number']))
    send_self_email('ACTION REQUIRED: cancellation request received', request, template="email/cancel.txt", context=context, devs_only=False)
    sa.cancellation_requested = True
    sa.save(update_fields=['cancellation_requested'])
    return redirect(settings.PERMA_SUBSCRIPTION_CANCELED_REDIRECT_URL)


@user_passes_test_or_403(lambda user: user.is_staff)
@require_http_methods(["POST"])
@sensitive_post_parameters('encrypted_data')
def update_statuses(request):
    csv_file = request.FILES['csv_file']
    skip_lines(csv_file, 4)
    for row in in_mem_csv_to_dict_reader(csv_file):
        reference = row['Merchant Reference Code']
        status = row['Status'].capitalize()
        try:
            sa = SubscriptionAgreement.objects.filter(subscription_request__reference_number=reference).get()
        except ObjectDoesNotExist:
            if settings.RAISE_IF_SUBSCRIPTION_NOT_FOUND:
                log_level = logging.ERROR
            else:
                log_level = logging.INFO
            logger.log(log_level, "CyberSource reports a subscription {}: no corresponding record found".format(reference))
            continue
        except MultipleObjectsReturned:
            if settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND:
                log_level = logging.ERROR
            else:
                log_level = logging.INFO
            logger.log(log_level, "Multiple subscription requests associated with {}.".format(reference))
            continue

        sa.status = status
        sa.paid_through = sa.calculate_paid_through_date_from_reported_status(status)
        sa.full_clean()
        sa.save(update_fields=['status', 'paid_through'])
        logger.info("Updated subscription status for {} to {}".format(reference, status))

    return render(request, 'generic.html', {'heading': "Statuses Updated",
                                            'message': "Check the application log for details."})
