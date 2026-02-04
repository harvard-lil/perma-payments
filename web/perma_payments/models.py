import calendar
import datetime
from dateutil.relativedelta import relativedelta
import random
from uuid import uuid4
from polymorphic.models import PolymorphicModel
from pytz import timezone
from simple_history.models import HistoricalRecords

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, IntegrityError

from .security import encrypt_for_storage, stringify_data
from perma_payments.tests import trace

import logging
logger = logging.getLogger(__name__)

#
# CONSTANTS
#

RN_SET = "0123456789"
REFERENCE_NUMBER_PREFIX = "PERMA"
STANDING_STATUSES = ['Current', 'Hold']
CUSTOMER_TYPES = ['Registrar', 'Individual']


#
# HELPERS
#

def generate_reference_number(suffix):
    """
    Generate a unique, human-friendly reference number. Based on Perma GUID generation.

    Only make 100 attempts:
    If there are frequent collisions, expand the keyspace or change the prefix.
    """

    # http://book.pythontips.com/en/latest/for_-_else.html#else-clause
    for i in range(100):
        rn = f"{REFERENCE_NUMBER_PREFIX}-{''.join(random.choices(RN_SET, k=4))}-{''.join(random.choices(RN_SET, k=4))}-{suffix}"
        if is_ref_number_available(rn, suffix):
            break
    else:
        raise Exception("No valid reference_number found in 100 attempts.")
    return rn


def generate_subscription_reference_number():
    return generate_reference_number('S')

def generate_purchase_reference_number():
    return generate_reference_number('P')

def generate_change_reference_number():
    return generate_reference_number('C')

def generate_update_reference_number():
    return generate_reference_number('U')

def is_ref_number_available(rn, suffix):
    model = {
        'S': SubscriptionRequest,
        'P': PurchaseRequest,
        'C': ChangeRequest,
        'U': UpdateRequest,
    }
    return not model[suffix].objects.filter(reference_number=rn).exists()


def last_day_of_month(now):
    _, num_days = calendar.monthrange(now.year, now.month)
    return datetime.datetime(now.year, now.month, num_days, tzinfo=now.tzinfo)


def this_day_next_year(now):
    # relativedelta handles leap years: 2/29 -> 2/28
    return now + relativedelta(years=1)


def just_before_midnight(dt):
    return dt.replace(hour=23, minute=59, second=59)


#
# CLASSES
#

class SubscriptionAndPurchaseMixin(models.Model):
    """
    Fields common to SubscriptionAgreements and PurchaseRequests
    """

    class Meta:
        abstract = True

    customer_pk = models.IntegerField()
    customer_type = models.CharField(
        max_length=20,
        choices=((key, key) for key in CUSTOMER_TYPES)
    )
    created_date = models.DateTimeField(auto_now_add=True)
    
    # Payment provider fields
    payment_provider = models.CharField(
        max_length=30,
        choices=((p, p) for p in settings.PAYMENT_PROVIDERS.keys()),
        db_index=True,
        help_text="The payment provider managing this subscription"
    )
    provider_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Provider-specific identifiers (e.g., payment_token, customer_id, subscription_id)"
    )


class SubscriptionAgreement(SubscriptionAndPurchaseMixin):
    """
    A Subscription Agreement comprises:
        a) A request to pay an amount, on a schedule, with a particular card and particular billing address
        b) The payment provider's initial response to the request.
           If approved, provider-specific identifiers will be stored in provider_data.
        c) Any subsequent updates from the payment provider about attempted scheduled payments.
           Indicates whether payments were successful and the agreement still stands.

    Supported payment providers:
        - cybersource_legacy: CyberSource Secure Acceptance Web/Mobile (redirect-based)
        - cybersource_rest: CyberSource REST API with Flex Microform (embedded)
        - stripe: Stripe Checkout/Payment Elements

    Provider-specific data is stored in provider_data JSONField:
        - cybersource_legacy: {"payment_token": "..."}
        - cybersource_rest: {"customer_id": "...", "payment_instrument_id": "...", "subscription_id": "..."}
        - stripe: {"customer_id": "cus_...", "subscription_id": "sub_...", "payment_method_id": "pm_..."}
    """

    class Meta:
        indexes = [
            # See SubscriptionAgreement.customer_standing_subscription() for the query this supports.
            models.Index(
                fields=["customer_pk", "customer_type", "id"],
                name="pp_sa_stand_cust_id_idx",
                condition=models.Q(status__in=STANDING_STATUSES),
            ),
            models.Index(
                fields=["customer_pk", "customer_type", "paid_through", "id"],
                name="pp_sa_canc_paid_thr_idx",
                condition=models.Q(status="Canceled", paid_through__isnull=False),
            ),
        ]

    def __str__(self):
        return 'SubscriptionAgreement {}'.format(self.id)

    history = HistoricalRecords()
    
    status = models.CharField(
        max_length=20,
        choices=(
            # Before we have received a definitive response from the payment provider
            ('Pending', 'Pending'),
            # The payment provider has rejected the request; no payment token/subscription ID was issued
            ('Rejected', 'Rejected'),
            # The user did not submit payment information
            ('Aborted', 'Aborted'),
            #
            # The provider approved the request and a payment token/subscription ID was issued.
            # The subscription can lapse, etc. at any point thereafter.
            # The following status values may be reported by the provider:
            #
            # The subscription has been canceled.
            ('Canceled', 'Canceled'),
            # All payments have been processed (installments subscriptions).
            # You see this status one or two days after the last payment is processed.
            # (Should never be returned to Perma Payments, since we are not selling installment plans.)
            ('Completed', 'Completed'),
            # The subscription is active, and the payments are up to date.
            ('Current', 'Current'),
            # The subscription is on hold because all payment attempts have failed
            # or a scheduled payment failed for a reason that requires intervention.
            ('Hold', 'Hold'),
            # The subscription has been updated and a new subscription ID has been assigned to it.
            # (Should never be returned to Perma Payments, since our accounts are not
            # configured to use 16-digit format-preserving payment tokens.)
            ('Superseded', 'Superseded')
        )
    )
    updated_date = models.DateTimeField(auto_now=True)
    paid_through = models.DateTimeField(
        null=True,
        blank=True
    )
    cancellation_requested = models.BooleanField(
        default=False
    )
    current_link_limit = models.CharField(blank=True, null=True, max_length=20)
    current_frequency = models.CharField(blank=True, null=True, max_length=20)
    current_rate = models.DecimalField(
        max_digits=19,
        decimal_places=2,
        blank=True,
        null=True
    )
    current_link_limit_effective_timestamp = models.DateTimeField(
        null=True,
        blank=True
    )

    @classmethod
    def customer_standing_subscription(cls, customer_pk, customer_type):
        standing_filter = models.Q(customer_pk=customer_pk) & models.Q(customer_type=customer_type) & (
            models.Q(status__in=STANDING_STATUSES) | (
                models.Q(status="Canceled") &
                models.Q(paid_through__gte=datetime.datetime.now(tz=timezone(settings.TIME_ZONE)))
            )
        )

        standing = cls.objects.filter(standing_filter).order_by('id')
        count = len(standing)
        if count == 0:
            return None
        if count > 1:
            logger.error("{} {} has multiple standing subscriptions ({})".format(customer_type, customer_pk, count))
            if settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND:
                raise cls.MultipleObjectsReturned
        # In the extremely unlikely (incorrect!) condition that a customer has multiple standing subscriptions,
        # return the oldest. Probably, something went wrong with an update request;
        # we should cancel/delete the new subscription(s), use the original, and if needed update the original one.
        return standing[0]


    def can_be_altered(self):
        return self.status in STANDING_STATUSES and not self.cancellation_requested

    def calculate_paid_through_date_from_reported_status(self, status):
        if status == 'Current':
            frequency = self.current_frequency
            now = datetime.datetime.now(tz=timezone(settings.TIME_ZONE))
            if frequency == 'monthly':
                # Monthly customers are charged on the 1st of the month.
                # Any 'current' monthly customer is paid through the end of the month.
                return just_before_midnight(last_day_of_month(now))
            elif frequency == 'annually':
                # Annual customers are charged on the anniversary of their subscription date.
                # If that day has already passed this year:
                #    a 'current' annual customer is paid through their anniversary, NEXT year.
                # If that day has not yet passed this year:
                #    a 'current' annual customer is paid through their anniversary THIS year.
                # If today is the anniversary:
                #    we can't know whether the provider has attempted a charge yet.
                #    Customer is paid through today, but tomorrow is a mystery.
                #    See settings.GRACE_PERIOD for complete discussion
                anniversary_this_year = self.created_date.replace(year=now.year)
                if anniversary_this_year < now:
                    return just_before_midnight(this_day_next_year(anniversary_this_year))
                elif anniversary_this_year == now:
                    return just_before_midnight(now + relativedelta(days=settings.GRACE_PERIOD))
                else:
                    return just_before_midnight(anniversary_this_year)
            # We only offer monthly and annual subscriptions.
            # If we change our minds, we need more logic here.
            logger.error("No code for calculating paid-through date for subscriptions recurring {}".format(frequency))
        return self.paid_through


    def update_after_payment_decision(self, request, decision, redacted_response):
        link_limit = request.link_limit
        link_limit_effective_timestamp = request.link_limit_effective_timestamp
        rate = request.recurring_amount
        if isinstance(request, SubscriptionRequest):
            frequency = request.recurring_frequency
        elif isinstance(request, ChangeRequest):
            frequency = request.subscription_agreement.current_frequency
        else:
            raise NotImplementedError()

        provider_name = self.payment_provider
        decision_map = {
            # Successful transaction. Reason codes 100 and 110.
            'ACCEPT': {
                'status': 'Current',
                'current_link_limit': link_limit,
                'current_link_limit_effective_timestamp': link_limit_effective_timestamp,
                'current_rate': rate,
                'current_frequency': frequency,
                'log_level': logging.INFO,
                'message': "{} for {} {} accepted.".format(str(request), self.customer_type, self.customer_pk)
            },
            # Authorization was declined; however, the capture may still be possible.
            # Review payment details. See reason codes 200, 201, 230, and 520.
            # (for now, we are treating this like 'ACCEPT', until we see an example in real life and can improve the logic)
            'REVIEW': {
                'status': 'Current',
                'current_link_limit': link_limit,
                'current_link_limit_effective_timestamp': link_limit_effective_timestamp,
                'current_rate': rate,
                'current_frequency': frequency,
                'log_level': logging.ERROR,
                'message': "{} for {} {} flagged for review by {}. Please investigate ASAP. Redacted response: {}".format(str(request), self.customer_type, self.customer_pk, provider_name, redacted_response)
            },
            # Transaction was declined. See reason codes 102, 200, 202, 203,
            # 204, 205, 207, 208, 210, 211, 221, 222, 230, 231, 232, 233,
            # 234, 236, 240, 475, 476, and 481.
            'DECLINE': {
                'status': 'Rejected',
                'log_level': logging.WARNING,
                'message': "{} for {} {} declined by {}. Redacted response: {}".format(str(request), self.customer_type, self.customer_pk, provider_name, redacted_response)
            },
            # Access denied, page not found, or internal server error.
            # See reason codes 102, 104, 150, 151 and 152.
            'ERROR': {
                'status': 'Rejected',
                'log_level': logging.ERROR,
                'message': "Error submitting {} to {} for {} {}. Redacted response: {}".format(str(request), provider_name, self.customer_type, self.customer_pk, redacted_response)
            },
            # The customer did not accept the service fee conditions,
            # or the customer canceled the transaction.
            'CANCEL': {
                'status': 'Aborted',
                'log_level': logging.INFO,
                'message': "{} aborted by {} {}.".format(str(request), self.customer_type, self.customer_pk)
            }
        }
        mapped = decision_map.get(decision, {
            # Keep 'Pending' until we review and figure out what is going on
            'status': 'Pending',
            'log_level': logging.ERROR,
            'message': "Unexpected decision from {} regarding {} for {} {}. Please investigate ASAP. Redacted response: {}".format(provider_name, str(request), self.customer_type, self.customer_pk, redacted_response)
        })
        self.status = mapped['status']
        if mapped.get('current_link_limit'):
            self.current_link_limit = mapped['current_link_limit']
        if mapped.get('current_link_limit_effective_timestamp'):
            self.current_link_limit_effective_timestamp = mapped['current_link_limit_effective_timestamp']
        if mapped.get('current_rate'):
            self.current_rate = mapped['current_rate']
        if mapped.get('current_frequency'):
            self.current_frequency = mapped['current_frequency']
        self.paid_through = self.calculate_paid_through_date_from_reported_status(self.status)
        self.save(update_fields=['status', 'current_link_limit', 'current_link_limit_effective_timestamp', 'current_rate', 'current_frequency', 'paid_through'])
        logger.log(mapped['log_level'], mapped['message'])


class OutgoingTransaction(PolymorphicModel):
    """
    Base model for all payment requests we send to providers.
    """
    def __str__(self):
        return 'OutgoingTransaction {}'.format(self.id)

    transaction_uuid = models.UUIDField(
        default=uuid4,
        help_text="A unique ID for this 'transaction'. " +
                  "Intended to protect against duplicate transactions."
    )
    request_datetime = models.DateTimeField(auto_now_add=True)

    def get_formatted_datetime(self):
        """
        Returns the request_datetime in ISO 8601 format.
        """
        return self.request_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")


class PurchaseFields(models.Model):
    """
    Abstract base class to hold fields used for all purchases
    """

    class Meta:
        abstract = True

    currency = models.CharField(
        max_length=3,
        default='USD'
    )
    locale = models.CharField(
        max_length=5,
        default='en-us'
    )
    payment_method = models.CharField(
        max_length=30,
        default='card'
    )
    # N.B. some provider test environments return error codes for certain amounts, by design.
    # Try to charge under $1,000 or over $10,000 when testing to avoid issues.
    amount = models.DecimalField(
        max_digits=19,
        decimal_places=2,
        help_text="Amount to be charged immediately"
    )


class SubscriptionFields(PurchaseFields):
    """
    Abstract base class to hold fields used to create a new subscription
    or change an existing one.
    """

    class Meta:
        abstract = True

    link_limit = models.CharField(
        max_length=20,
        help_text="For internal use only: link limit associated with the subscription"
    )
    link_limit_effective_timestamp = models.DateTimeField(
        help_text="For internal use only: when Perma should apply the new link limit associated with this purchase"
    )
    # N.B. some provider test environments return error codes for certain amounts, by design.
    # Try to charge under $1,000 or over $10,000 when testing to avoid issues.
    recurring_amount = models.DecimalField(
        max_digits=19,
        decimal_places=2,
        help_text="Amount to be charged repeatedly, beginning on recurring_start_date"
    )

    @property
    def customer_pk(self):
        return self.subscription_agreement.customer_pk

    @property
    def customer_type(self):
        return self.subscription_agreement.customer_type


class SubscriptionRequest(OutgoingTransaction, SubscriptionFields):
    """
    All (non-confidential) specifics of a customer's request for a subscription.

    Useful for:
    1) reconstructing a customer's account history;
    2) resending failed requests;
    3) comparing notes with provider records
    """
    def __str__(self):
        return 'SubscriptionRequest {}'.format(self.id)

    subscription_agreement = models.OneToOneField(
        SubscriptionAgreement,
        related_name='subscription_request',
        on_delete=models.CASCADE
    )
    transaction_type = models.CharField(
        max_length=30,
        default='sale,create_payment_token'
    )
    reference_number = models.CharField(
        max_length=32,
        default=generate_subscription_reference_number,
        help_text="Unique ID for this subscription. " +
                  "Subsequent charges, automatically made by the payment provider on the recurring schedule, " +
                  "will all be associated with this reference number."
    )
    recurring_start_date = models.DateField(
        help_text="Date on which to commence charging recurring_amount"
    )
    recurring_frequency = models.CharField(
        max_length=20,
        choices=(
            ('weekly', 'weekly'),
            ('bi-weekly', 'bi-weekly (every 2 weeks)'),
            ('quad-weekly', 'quad-weekly (every 4 weeks)'),
            ('monthly', 'monthly'),
            ('semi-monthly', 'semi-monthly (1st and 15th of each month)'),
            ('quarterly', 'quarterly'),
            ('semi-annually', 'semi-annually (twice every year)'),
            ('annually', 'annually')
        )
    )

    def get_formatted_start_date(self):
        """
        Returns the recurring_start_date in YYYYMMDD format.
        """
        return self.recurring_start_date.strftime("%Y%m%d")


class ChangeRequest(OutgoingTransaction, SubscriptionFields):
    """
    All (non-confidential) specifics of a customer's request to switch tiers.
    """
    def __str__(self):
        return 'ChangeRequest {}'.format(self.id)

    subscription_agreement = models.ForeignKey(
        SubscriptionAgreement,
        related_name='change_requests',
        on_delete=models.CASCADE
    )
    transaction_type = models.CharField(
        max_length=30,
        default='sale,update_payment_token'
    )
    reference_number = models.CharField(
        max_length=32,
        default=generate_change_reference_number,
        help_text="Unique ID for this change request."
    )

    def save(self, *args, **kwargs):
        if not self.amount:
            self.transaction_type = 'update_payment_token'
        else:
            self.transaction_type = 'sale,update_payment_token'
        return super(ChangeRequest, self).save(*args, **kwargs)


class UpdateRequest(OutgoingTransaction):
    """
    All (non-confidential) specifics of a customer's request to update their payment information.

    Useful for:
    1) reconstructing a customer's account history;
    2) resending failed requests;
    3) comparing notes with provider records
    """
    def __str__(self):
        return 'UpdateRequest {}'.format(self.id)

    subscription_agreement = models.ForeignKey(
        SubscriptionAgreement,
        related_name='update_requests',
        on_delete=models.CASCADE
    )
    transaction_type = models.CharField(
        max_length=30,
        default='update_payment_token'
    )
    reference_number = models.CharField(
        max_length=32,
        default=generate_update_reference_number,
        help_text="Unique ID for this update request."
    )

    @property
    def customer_pk(self):
        return self.subscription_agreement.customer_pk

    @property
    def customer_type(self):
        return self.subscription_agreement.customer_type


class PurchaseRequest(SubscriptionAndPurchaseMixin, OutgoingTransaction, PurchaseFields):
    """
    A one-time request to purchase more links, independent of any subscription.
    """
    class Meta:
        indexes = [
            # Supports PurchaseRequestResponse.customer_unacknowledged()/customer_history()
            # which filter on related_request__customer_pk/customer_type.
            models.Index(
                fields=["customer_pk", "customer_type"],
                name="pp_pr_custtype_idx",
            ),
        ]

    def __str__(self):
        return 'PurchaseRequest {}'.format(self.id)

    transaction_type = models.CharField(
        max_length=30,
        default='sale'
    )
    reference_number = models.CharField(
        max_length=32,
        default=generate_purchase_reference_number,
        help_text="Unique ID for this purchase."
    )
    link_quantity = models.PositiveIntegerField()


class Response(PolymorphicModel):
    """
    Audit log for synchronous redirect-based payment callbacks.
    
    This model is used by providers that follow a redirect callback pattern:
    1. User is redirected to provider's payment page
    2. After payment, provider redirects back with signed POST data
    3. We validate and save the response here, linked to the OutgoingTransaction
    
    Used by: CyberSource Legacy, CyberSource REST
    
    For async webhook-based providers (e.g., Stripe), see WebhookLog instead.
    
    Most fields are nullable to handle malformed responses gracefully.
    """
    def __str__(self):
        return 'Response {}'.format(self.id)

    def clean(self, *args, **kwargs):
        super(Response, self).clean(*args, **kwargs)
        if not self.full_response:
            raise ValidationError({'full_response': 'This field cannot be blank.'})

    # We can't guarantee providers will send us these fields, though we sure hope so
    decision = models.CharField(
        blank=True,
        null=True,
        max_length=7,
        choices=(
            ('ACCEPT', 'ACCEPT'),
            ('REVIEW', 'REVIEW'),
            ('DECLINE', 'DECLINE'),
            ('ERROR', 'ERROR'),
            ('CANCEL', 'CANCEL'),
        )
    )
    reason_code = models.IntegerField(blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    # required
    full_response = models.BinaryField(
        help_text="The full response, encrypted, in case we ever need it."
    )
    encryption_key_id = models.IntegerField()

    @property
    def related_request(self):
        """
        Must be implemented by children
        """
        raise NotImplementedError

    @property
    def subscription_agreement(self):
        """
        Must be implemented by children
        """
        raise NotImplementedError

    @property
    def customer_pk(self):
        """
        Must be implemented by children
        """
        raise NotImplementedError

    @property
    def customer_type(self):
        """
        Must be implemented by children
        """
        raise NotImplementedError

    @classmethod
    def save_new_with_encrypted_full_response(cls, response_class, full_response, fields):
        """
        Saves a new instance of type response_class, encrypting the
        'full_response' field
        """
        data = {
            'encryption_key_id': settings.STORAGE_ENCRYPTION_KEYS['id'],
            'full_response': encrypt_for_storage(
                stringify_data(full_response)
            )
        }
        data.update(fields)
        response = response_class(**data)
        # I'm not sure it makes sense to validate before saving here.
        # If there's some problem, what do we want to do?
        # Might as well just wait for any db integrity errors, right?
        # It's not like the payment provider will listen for a 400 response, and
        # we should be notified, which will happen automatically if save fails.
        #
        # response.full_clean()
        response.save()
        return response

    @classmethod
    def save_callback_response(
        cls,
        outgoing_transaction,
        *,
        decision: str,
        message: str,
        raw_response: dict,
        provider_data: dict | None = None,
    ):
        """
        Save a response from a redirect-based payment callback.
        
        Creates the appropriate Response subclass based on the OutgoingTransaction type,
        encrypts and stores the raw response, and updates the SubscriptionAgreement.
        
        Args:
            outgoing_transaction: The original request (SubscriptionRequest, PurchaseRequest, etc.)
            decision: Normalized decision - 'ACCEPT', 'DECLINE', 'ERROR', 'CANCEL', 'REVIEW'
            message: Human-readable message from the provider
            raw_response: Full response dict for encrypted storage/debugging
            provider_data: Provider-specific data (e.g., reason_code, payment_token)
        """
        provider_data = provider_data or {}
        reason_code = provider_data.get('reason_code')
        success = decision in ('ACCEPT', 'REVIEW')

        if isinstance(outgoing_transaction, SubscriptionRequest):
            response = Response.save_new_with_encrypted_full_response(
                SubscriptionRequestResponse,
                raw_response,
                {
                    'related_request': outgoing_transaction,
                    'decision': decision,
                    'reason_code': reason_code,
                    'message': message,
                    'payment_token': provider_data.get('payment_token', ''),
                }
            )
            trace.db(response, title='SubscriptionRequestResponse')

            sa = outgoing_transaction.subscription_agreement
            if success and provider_data:
                sa.provider_data = provider_data
                sa.save(update_fields=['provider_data'])

            sa.update_after_payment_decision(outgoing_transaction, decision, raw_response)

        elif isinstance(outgoing_transaction, PurchaseRequest):
            response = Response.save_new_with_encrypted_full_response(
                PurchaseRequestResponse,
                raw_response,
                {
                    'related_request': outgoing_transaction,
                    'decision': decision,
                    'reason_code': reason_code,
                    'message': message,
                }
            )
            trace.db(response, title='PurchaseRequestResponse')
            response.act_on_decision(raw_response)

        elif isinstance(outgoing_transaction, ChangeRequest):
            response = Response.save_new_with_encrypted_full_response(
                ChangeRequestResponse,
                raw_response,
                {
                    'related_request': outgoing_transaction,
                    'decision': decision,
                    'reason_code': reason_code,
                    'message': message,
                }
            )
            trace.db(response, title='ChangeRequestResponse')
            outgoing_transaction.subscription_agreement.update_after_payment_decision(
                outgoing_transaction, decision, raw_response
            )

        elif isinstance(outgoing_transaction, UpdateRequest):
            response = Response.save_new_with_encrypted_full_response(
                UpdateRequestResponse,
                raw_response,
                {
                    'related_request': outgoing_transaction,
                    'decision': decision,
                    'reason_code': reason_code,
                    'message': message,
                }
            )
            trace.db(response, title='UpdateRequestResponse')

        else:
            raise ValueError("Unexpected outgoing transaction type: {}".format(type(outgoing_transaction)))

        return response


class SubscriptionRequestResponse(Response):
    """
    All (non-confidential) specifics of the provider's response to a subscription request.
    """
    def __str__(self):
        return 'SubscriptionRequestResponse {}'.format(self.id)

    related_request = models.OneToOneField(
        SubscriptionRequest,
        related_name='subscription_request_response',
        on_delete=models.CASCADE
    )
    payment_token = models.CharField(
        max_length=255,
        blank=True,
        default=''
    )

    @property
    def subscription_agreement(self):
        return self.related_request.subscription_agreement

    @property
    def customer_pk(self):
        return self.related_request.subscription_agreement.customer_pk

    @property
    def customer_type(self):
        return self.related_request.subscription_agreement.customer_type


class ChangeRequestResponse(Response):
    """
    All (non-confidential) specifics of the provider's response to a change request.
    """
    def __str__(self):
        return 'ChangeRequestResponse {}'.format(self.id)

    related_request = models.OneToOneField(
        ChangeRequest,
        related_name='change_request_response',
        on_delete=models.CASCADE
    )

    @property
    def subscription_agreement(self):
        return self.related_request.subscription_agreement

    @property
    def customer_pk(self):
        return self.related_request.subscription_agreement.customer_pk

    @property
    def customer_type(self):
        return self.related_request.subscription_agreement.customer_type


class UpdateRequestResponse(Response):
    """
    All (non-confidential) specifics of the provider's response to an update request.
    """
    def __str__(self):
        return 'UpdateRequestResponse {}'.format(self.id)

    related_request = models.OneToOneField(
        UpdateRequest,
        related_name='update_request_response',
        on_delete=models.CASCADE
    )

    @property
    def subscription_agreement(self):
        return self.related_request.subscription_agreement

    @property
    def customer_pk(self):
        return self.related_request.subscription_agreement.customer_pk

    @property
    def customer_type(self):
        return self.related_request.subscription_agreement.customer_type


class PurchaseRequestResponse(Response):
    """
    All (non-confidential) specifics of the provider's response to a purchase request.
    """
    class Meta:
        indexes = [
            # Supports PurchaseRequestResponse.customer_unacknowledged():
            # inform_perma = true AND perma_acknowledged_at IS NULL
            models.Index(
                fields=["related_request"],
                name="pp_prr_unack_rel_idx",
                condition=models.Q(inform_perma=True, perma_acknowledged_at__isnull=True),
            ),
        ]

    def __str__(self):
        return 'PurchaseRequestResponse {}'.format(self.id)

    related_request = models.OneToOneField(
        PurchaseRequest,
        related_name='purchase_request_response',
        on_delete=models.CASCADE
    )
    inform_perma = models.BooleanField(
        default=False,
        help_text='Should Perma be informed that this customer has successfully purchased more links?'
    )
    perma_acknowledged_at = models.DateTimeField(
        blank=True,
        null=True
    )

    @classmethod
    def customer_unacknowledged(cls, customer_pk, customer_type):
        purchases = cls.objects.filter(
            inform_perma=True,
            perma_acknowledged_at__isnull=True,
            related_request__customer_pk=customer_pk,
            related_request__customer_type=customer_type
        ).select_related('related_request')
        return [{'id': purchase.pk, 'link_quantity': purchase.related_request.link_quantity} for purchase in purchases]

    @classmethod
    def customer_history(cls, customer_pk, customer_type):
        purchases = cls.objects.filter(
            inform_perma=True,
            related_request__customer_pk=customer_pk,
            related_request__customer_type=customer_type
        ).select_related('related_request')
        return [
            {
                'id': purchase.pk,
                'link_quantity': purchase.related_request.link_quantity,
                'date': purchase.related_request.request_datetime,
                'reference_number': purchase.related_request.reference_number,
            } for purchase in purchases
        ]

    @property
    def subscription_agreement(self):
        return None

    @property
    def customer_pk(self):
        return self.related_request.customer_pk

    @property
    def customer_type(self):
        return self.related_request.customer_type

    def act_on_decision(self, redacted_response):
        """
        Process the payment decision and update inform_perma status.
        """
        request = self.related_request
        provider_name = request.payment_provider
        decision_map = {
            # Successful transaction. Reason codes 100 and 110.
            'ACCEPT': {
                'inform_perma': True,
                'log_level': logging.INFO,
                'message': "{} for {} {} accepted.".format(str(request), request.customer_type, request.customer_pk)
            },
            # Authorization was declined; however, the capture may still be possible.
            # Review payment details. See reason codes 200, 201, 230, and 520.
            # (for now, we are treating this like 'ACCEPT', until we see an example in real life and can improve the logic)
            'REVIEW': {
                'inform_perma': True,
                'log_level': logging.ERROR,
                'message': "{} for {} {} flagged for review by {}. Please investigate ASAP. Redacted response: {}".format(str(request), request.customer_type, request.customer_pk, provider_name, redacted_response)
            },
            # Transaction was declined. See reason codes 102, 200, 202, 203,
            # 204, 205, 207, 208, 210, 211, 221, 222, 230, 231, 232, 233,
            # 234, 236, 240, 475, 476, and 481.
            'DECLINE': {
                'inform_perma': False,
                'log_level': logging.WARNING,
                'message': "{} for {} {} declined by {}. Redacted response: {}".format(str(request), request.customer_type, request.customer_pk, provider_name, redacted_response)
            },
            # Access denied, page not found, or internal server error.
            # See reason codes 102, 104, 150, 151 and 152.
            'ERROR': {
                'inform_perma': False,
                'log_level': logging.ERROR,
                'message': "Error submitting {} to {} for {} {}. Redacted response: {}".format(str(request), provider_name, request.customer_type, request.customer_pk, redacted_response)
            },
            # The customer did not accept the service fee conditions,
            # or the customer canceled the transaction.
            'CANCEL': {
                'inform_perma': False,
                'log_level': logging.INFO,
                'message': "{} aborted by {} {}.".format(str(request), request.customer_type, request.customer_pk)
            }
        }
        mapped = decision_map.get(self.decision, {
            # Keep 'False' until we review and figure out what is going on
            'inform_perma': False,
            'log_level': logging.ERROR,
            'message': "Unexpected decision from {} regarding {} for {} {}. Please investigate ASAP. Redacted response: {}".format(provider_name, str(request), request.customer_type, request.customer_pk, redacted_response)
        })
        self.inform_perma = mapped['inform_perma']
        self.save(update_fields=['inform_perma'])
        logger.log(mapped['log_level'], mapped['message'])


class WebhookLog(models.Model):
    """
    Audit log for async webhook-based payment events.
    
    This model is used by providers that send events via webhooks:
    1. Provider sends POST to our webhook endpoint
    2. We validate signature and process the event
    3. We log the event here and update SubscriptionAgreement as needed
    
    Unlike Response, webhook events are not tied to a specific OutgoingTransaction -
    they can be renewals, cancellations, or other lifecycle events that happen
    asynchronously after the initial subscription setup.
    
    Used by: Stripe
    
    For synchronous redirect-based providers (e.g., CyberSource), see Response instead.
    """
    
    def __str__(self):
        return f'WebhookLog {self.id} ({self.event_type})'
    
    # Provider identification
    provider = models.CharField(
        max_length=30,
        db_index=True,
        help_text="Payment provider that sent this webhook (e.g., 'stripe')"
    )
    
    # Event identification (provider's unique ID to prevent duplicate processing)
    event_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Provider's unique event ID (e.g., Stripe's evt_...)"
    )
    
    # Event details
    event_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Event type (e.g., 'invoice.paid', 'customer.subscription.deleted')"
    )
    
    # Link to our records (nullable - some events may not match a known agreement)
    subscription_agreement = models.ForeignKey(
        SubscriptionAgreement,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='webhook_logs',
        help_text="The SubscriptionAgreement this event relates to, if identifiable"
    )
    
    # Processing result
    processed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=(
            ('processed', 'Processed'),
            ('ignored', 'Ignored'),  # Valid event but no action needed
            ('unmatched', 'Unmatched'),  # Could not find related agreement
            ('error', 'Error'),
        ),
        default='processed',
    )
    status_message = models.TextField(
        blank=True,
        help_text="Human-readable description of processing result"
    )
    
    # Encrypted raw event for debugging
    raw_event = models.BinaryField(
        help_text="The full webhook payload, encrypted"
    )
    encryption_key_id = models.IntegerField()
    
    class Meta:
        # Prevent duplicate processing of the same event
        unique_together = [['provider', 'event_id']]
        indexes = [
            models.Index(fields=['provider', 'event_type']),
            models.Index(fields=['processed_at']),
        ]
    
    @classmethod
    def log_event(
        cls,
        *,
        provider: str,
        event_id: str,
        event_type: str,
        raw_event: dict,
        subscription_agreement: SubscriptionAgreement | None = None,
        status: str = 'processed',
        status_message: str = '',
    ):
        """
        Log a webhook event with encrypted raw payload.
        
        Returns the created WebhookLog, or None if this event_id was already processed.
        """
        
        try:
            log = cls(
                provider=provider,
                event_id=event_id,
                event_type=event_type,
                subscription_agreement=subscription_agreement,
                status=status,
                status_message=status_message,
                encryption_key_id=settings.STORAGE_ENCRYPTION_KEYS['id'],
                raw_event=encrypt_for_storage(stringify_data(raw_event)),
            )
            log.save()
            return log
        except IntegrityError:
            # Duplicate event_id - already processed
            logger.info(
                "Duplicate webhook event %s/%s ignored (already processed)",
                provider, event_id
            )
            return None
