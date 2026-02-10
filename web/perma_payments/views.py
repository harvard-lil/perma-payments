import csv
from datetime import datetime
from pytz import timezone
from functools import wraps
import io

from django.conf import settings
from perma_payments.tests import trace
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, ObjectDoesNotExist, MultipleObjectsReturned, PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render, redirect
from django.utils.timezone import make_aware
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .custom_errors import bad_request
from .email import send_self_email
from .models import (
    SubscriptionAgreement,
    SubscriptionRequest,
    ChangeRequest,
    UpdateRequest,
    PurchaseRequest,
    PurchaseRequestResponse,
)
from .providers.router import get_provider, get_checkout_provider
from .providers.base import CallbackValidationError, NoProviderAvailable
from .security import (
   InvalidTransmissionException,
   prep_for_perma,
   process_perma_transmission,
)

import logging
logger = logging.getLogger(__name__)

#
# UTILS
#

def get_provider_or_404(provider_name: str):
    """Get a payment provider by name or raise Http404."""
    try:
        return get_provider(provider_name)
    except (KeyError, NoProviderAvailable):
        logger.error("Unknown payment provider: %s", provider_name)
        raise Http404(f"Unknown payment provider: {provider_name}")


def get_checkout_provider_or_500(customer_pk, customer_type):
    """Get checkout provider or raise server error (500).
    
    NoProviderAvailable indicates misconfiguration or upstream issues,
    not a user error, so we let it propagate as a 500.
    """
    try:
        return get_checkout_provider(customer_pk, customer_type)
    except NoProviderAvailable:
        logger.error("No payment provider available - check configuration")
        raise


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
                                            'message': "Payment processing service for Perma.cc"})


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
    
    # Log the decrypted purchase data
    trace.log(
        title='Decrypted Purchase Data',
        lane='Server',
        data=data,
        explanation='Payload from Perma.cc decrypted from encrypted_data POST field',
    )

    # Get the appropriate payment provider
    provider = get_checkout_provider_or_500(data['customer_pk'], data['customer_type'])

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
            trace.db(p_request, title='PurchaseRequest')
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc purchase form: {}'.format(e))
        return bad_request(request)

    logger.info("Purchase request received for {} {} (provider: {})".format(
        data['customer_type'], data['customer_pk'], provider.name
    ))
    return provider.checkout_purchase(request, p_request)


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
    
    # Log the decrypted subscription data
    trace.log(
        title='Decrypted Subscribe Data',
        lane='Server',
        data=data,
        explanation='Payload from Perma.cc decrypted from encrypted_data POST field',
    )

    # The user must not already have a standing subscription.
    if SubscriptionAgreement.customer_standing_subscription(data['customer_pk'], data['customer_type']):
        return render(request, 'generic.html', {'heading': "Good News!",
                                                'message': "You already have a subscription to Perma.cc.<br>" +
                                                           "If you believe you have reached this page in error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})

    # Get the appropriate payment provider
    provider = get_checkout_provider_or_500(data['customer_pk'], data['customer_type'])

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
            trace.db(s_agreement, title='SubscriptionAgreement (Pending)')
            
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
            trace.db(s_request, title='SubscriptionRequest')
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc subscribe form: {}'.format(e))
        return bad_request(request)

    logger.info("Subscription request received for {} {} (provider: {})".format(
        data['customer_type'], data['customer_pk'], provider.name
    ))
    return provider.checkout_subscribe(request, s_request)


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
    
    # Log the decrypted change data
    trace.log(
        title='Decrypted Change Data',
        lane='Server',
        data=data,
        explanation='Payload from Perma.cc decrypted from encrypted_data POST field',
    )

    # The user must have a subscription that can be updated.
    sa = SubscriptionAgreement.customer_standing_subscription(data['customer_pk'], data['customer_type'])
    if not sa or not sa.can_be_altered():
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})
    
    trace.db(sa, title='SubscriptionAgreement (existing)', action='Fetch')

    # Get the provider for this subscription
    provider = get_provider_or_404(sa.payment_provider)

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
        trace.db(c_request, title='ChangeRequest')
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc change form: {}'.format(e))
        return bad_request(request)

    logger.info("Change request received for {} {} (provider: {})".format(
        data['customer_type'], data['customer_pk'], provider.name
    ))
    return provider.checkout_change(request, c_request)


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
    
    # Log the decrypted update data
    trace.log(
        title='Decrypted Update Data',
        lane='Server',
        data=data,
        explanation='Payload from Perma.cc decrypted from encrypted_data POST field',
    )

    # The user must have a subscription that can be updated.
    sa = SubscriptionAgreement.customer_standing_subscription(data['customer_pk'], data['customer_type'])
    if not sa or not sa.can_be_altered():
        return render(request, 'generic.html', {'heading': "We're Having Trouble With Your Update Request",
                                                'message': "We can't find any active subscriptions associated with your account.<br>" +
                                                           "If you believe this is an error, please contact us at <a href='mailto:{0}?subject=Our%20Subscription'>{0}</a>.".format(settings.DEFAULT_CONTACT_EMAIL)})
    
    trace.db(sa, title='SubscriptionAgreement (existing)', action='Fetch')

    # Get the provider for this subscription
    provider = get_provider_or_404(sa.payment_provider)

    # The update request fields must each be valid.
    try:
        u_request = UpdateRequest(
            subscription_agreement=sa,
        )
        u_request.full_clean()
        u_request.save()
        trace.db(u_request, title='UpdateRequest')
    except ValidationError as e:
        logger.warning('Invalid POST from Perma.cc update form: {}'.format(e))
        return bad_request(request)

    logger.info("Update payment information request received for {} {} (provider: {})".format(
        data['customer_type'], data['customer_pk'], provider.name
    ))
    return provider.checkout_update(request, u_request)


@csrf_exempt
@require_http_methods(["POST"])
@sensitive_post_parameters(*SENSITIVE_POST_PARAMETERS)
def cybersource_callback(request):
    """
    Legacy callback URL for CyberSource Secure Acceptance.
    
    This endpoint exists for backward compatibility with CyberSource Business Center
    configurations that use the old /cybersource-callback/ URL. It simply delegates
    to the cybersource_legacy provider's webhook handler.
    
    New configurations should use /callback/cybersource_legacy/ instead.
    """
    return provider_webhook(request, 'cybersource_legacy')


@csrf_exempt
@require_http_methods(["GET", "POST"])
def provider_webhook(request, provider_name):
    """
    Generic callback/webhook endpoint for payment providers.
    
    Routes to the appropriate provider based on the URL parameter.
    URL pattern: /callback/<provider_name>/

    Providers can return a string, raise CallbackValidationError, or return
    a custom HttpResponse.
    """
    provider = get_provider_or_404(provider_name)
    
    # Trace incoming webhook request from provider
    provider_lane = provider_name.title().replace('_', ' ')
    trace.network_request(
        from_lane=provider_lane,
        to_lane='Server',
        method=request.method,
        url=request.build_absolute_uri(),
        body=dict(request.POST) if request.POST else None,
        title=f'{provider_lane} Webhook',
    )
    
    try:
        out = provider.handle_webhook(request)
        if isinstance(out, str):
            response = render(request, 'generic.html', {
                'heading': f'{provider_name.title()} Callback',
                'message': out,
            })
            trace.network_response(
                from_lane='Server',
                to_lane=provider_lane,
                status=response.status_code,
                body={'message': out},
                title='Webhook Response',
            )
            return response
        # HttpResponse returned directly by provider
        trace.network_response(
            from_lane='Server',
            to_lane=provider_lane,
            status=out.status_code,
            title='Webhook Response',
        )
        return out
    except CallbackValidationError as err:
        logger.warning("Callback validation failed for %s: %s", provider_name, err)
        response = render(request, 'generic.html', {
            'heading': f'{provider_name.title()} Callback',
            'message': err.display_message,
        }, status=400)
        trace.network_response(
            from_lane='Server',
            to_lane=provider_lane,
            status=400,
            body={'error': err.display_message},
            title='Webhook Error',
        )
        return response


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
    Records a cancellation request from Perma.cc.
    
    If the provider supports programmatic cancellation, cancels immediately via API.
    Otherwise, flags the subscription and emails staff to cancel manually.
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

    merchant_reference_number = sa.subscription_request.reference_number
    logger.info("Cancellation request received from {} {} for {}".format(
        data['customer_pk'], data['customer_type'], merchant_reference_number))
    
    # Build base context for emails
    context = {
        'customer_pk': data['customer_pk'],
        'customer_type': data['customer_type'],
        'perma_url': settings.PERMA_URL,
        'individual_detail_path': settings.INDIVIDUAL_DETAIL_PATH,
        'registrar_detail_path': settings.REGISTRAR_DETAIL_PATH,
        'registrar_users_path': settings.REGISTRAR_USERS_PATH,
        'merchant_reference_number': merchant_reference_number,
    }
    
    # Try programmatic cancellation if provider supports it
    provider = get_provider_or_404(sa.payment_provider)
    subscription_id = sa.provider_data.get('subscription_id')
    
    if provider.supports_cancellation and subscription_id:
        provider.cancel_subscription(subscription_id)
        logger.info("Subscription %s canceled via %s API", subscription_id, provider.name)
        
        # Update subscription status
        sa.status = 'Canceled'
        sa.cancellation_requested = True
        sa.save(update_fields=['status', 'cancellation_requested'])
        
        # Send informational email to staff
        context.update({
            'provider_name': provider.name,
            'subscription_id': subscription_id,
        })
        send_self_email(
            'Subscription canceled: {} {}'.format(data['customer_type'], data['customer_pk']),
            request,
            template="email/cancel_completed.txt",
            context=context,
            devs_only=False
        )
        
        return redirect(settings.PERMA_SUBSCRIPTION_CANCELED_REDIRECT_URL)
    
    if not provider.supports_cancellation:
        logger.info("Provider %s does not support programmatic cancellation, using manual flow", provider.name)
    elif not subscription_id:
        logger.info("No subscription_id in provider_data, using manual cancellation flow")
    
    # Fall back to manual cancellation flow
    context['provider_name'] = provider.name
    context['search_url'] = provider.manual_cancellation_url
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
            logger.log(log_level, "Subscription status CSV reports subscription {}: no corresponding record found".format(reference))
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
