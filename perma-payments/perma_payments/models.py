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
from django.db import models

from .security import encrypt_for_storage, stringify_data

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

def generate_reference_number():
    """
    Generate a unique, human-friendly reference number. Based on Perma GUID generation.

    Only make 100 attempts:
    If there are frequent collisions, expand the keyspace or change the prefix.
    """
    # temp until we upgrade to 3.6 and random.choices is available
    def choices(chars, k):
        return ''.join(random.choice(chars) for _ in range(k))

    # http://book.pythontips.com/en/latest/for_-_else.html#else-clause
    for i in range(100):
        rn = "PERMA-{}-{}".format(
            choices(RN_SET, k=4),
            choices(RN_SET, k=4)
        )
        if is_ref_number_available(rn):
            break
    else:
        raise Exception("No valid reference_number found in 100 attempts.")
    return rn


def is_ref_number_available(rn):
    return not SubscriptionRequest.objects.filter(reference_number=rn).exists()


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

class SubscriptionAgreement(models.Model):
    """
    A Subscription Agreement comprises:
        a) A request to pay an amount, on a schedule, with a particular card and particular billing address
        b) CyberSource's initial response to the request.
           If CyberSource approves the subscription request,
           a 'Payment Token', also known as a 'Subscription ID', will be included in the response.
        c) Any subsequent updates from CyberSource about attempted scheduled payments
           associated with the Subscription ID. Indicates whether payments were successful and
           the agreement still stands.

    N.B. Perma-Payments does NOT support 16-digit format-preserving subscription IDs.

    If a CyberSource account is configured to use a 16-digit format-preserving Payment Token/Subscription ID,
    and if the customer subsequently updates the card number, CyberSource will mark the original Payment Token
    as obsolete ("superseded") and issue a new Payment Token/Subscription ID.

    Perma-Payments only supports unchanging, updateable Payment Tokens,
    which are the CyberSource default as of 8/16/17.

    Perma-Payments will log an error if any 16-digit Payment Tokens are received.
    """
    def __str__(self):
        return 'SubscriptionAgreement {}'.format(self.id)

    history = HistoricalRecords()
    customer_pk = models.IntegerField()
    customer_type = models.CharField(
        max_length=20,
        choices=((key, key) for key in CUSTOMER_TYPES)
    )
    status = models.CharField(
        max_length=20,
        choices=(
            # Before we have received a definitive response from CyberSource
            ('Pending', 'Pending'),
            # CyberSource has rejected the request; no payment token/subscription ID was issued
            ('Rejected', 'Rejected'),
            # The user did not submit payment information
            ('Aborted', 'Aborted'),
            #
            # CyberSource approved the request and a payment token/subscription ID was issued
            # The subscription can lapse, etc. at any point thereafter.
            # CyberSource will report one of the below status values for each initially-approved subscription in the Business Center
            # from https://ebctest.cybersource.com/ebctest/help/en/index.html#page/Business_Center_Help/sub_search_results.htm
            #
            # The subscription has been canceled.
            ('Canceled', 'Canceled'),
            # All payments have been processed (installments subscriptions).
            # You see this status one or two days after the last payment is processed.
            # (As of 8/16/17, should never be returned to Perma Payments, since we are not selling installment plans.)
            ('Completed', 'Completed'),
            # The subscription is active, and the payments are up to date.
            ('Current', 'Current'),
            # The subscription is on hold because all payment attempts have failed
            # or a scheduled payment failed for a reason that requires your intervention.
            # You can see the subscriptions on hold in the daily Payment Exception Report.
            # For more information about holding profiles, see the Payment Tokenization documentation:
            # http://apps.cybersource.com/library/documentation/dev_guides/Payment_Tokenization/html
            ('Hold', 'Hold'),
            # The subscription has been updated and a new subscription ID has been assigned to it.
            # (As of 8/16/17, should never be returned to Perma Payments, since our account is not
            # configured to use 16-digit format-preserving payment tokens.)
            ('Superseded', 'Superseded')
        )
    )
    created_date = models.DateTimeField(auto_now_add=True)
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
                #    we can't know whether CyberSource has attempted a charge yet.
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


    def update_after_cs_decision(self, request, decision, redacted_response):
        link_limit = request.link_limit
        link_limit_effective_timestamp = request.link_limit_effective_timestamp
        rate = request.recurring_amount
        if isinstance(request, SubscriptionRequest):
            frequency = request.recurring_frequency
        elif isinstance(request, ChangeRequest):
            frequency = request.subscription_agreement.current_frequency
        else:
            raise NotImplementedError()

        decision_map = {
            # Successful transaction. Reason codes 100 and 110.
            'ACCEPT': {
                'status': 'Current',
                'current_link_limit': link_limit,
                'current_link_limit_effective_timestamp': link_limit_effective_timestamp,
                'current_rate': rate,
                'current_frequency': frequency,
                'log_level': logging.INFO,
                'message': "{} {} for {} {} accepted.".format(type(request), request.pk, self.customer_type, self.customer_pk)
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
                'message': "{} {} for {} {} flagged for review by CyberSource. Please investigate ASAP. Redacted response: {}".format(type(request), request.pk, self.customer_type, self.customer_pk, redacted_response)
            },
            # Transaction was declined.See reason codes 102, 200, 202, 203,
            # 204, 205, 207, 208, 210, 211, 221, 222, 230, 231, 232, 233,
            # 234, 236, 240, 475, 476, and 481.
            'DECLINE': {
                'status': 'Rejected',
                'log_level': logging.WARNING,
                'message': "{} {} for {} {} declined by CyberSource. Redacted response: {}".format(type(request), request.pk, self.customer_type, self.customer_pk, redacted_response)
            },
            # Access denied, page not found, or internal server error.
            # See reason codes 102, 104, 150, 151 and 152.
            'ERROR': {
                'status': 'Rejected',
                'log_level': logging.ERROR,
                'message': "Error submitting {} {} to CyberSource for {} {}. Redacted reponse: {}".format(type(request), request.pk, self.customer_type, self.customer_pk, redacted_response)
            },
            # The customer did not accept the service fee conditions,
            # or the customer canceled the transaction.
            'CANCEL': {
                'status': 'Aborted',
                'log_level': logging.INFO,
                'message': "{} {} aborted by {} {}.".format(type(request), request.pk, self.customer_type, self.customer_pk)
            }
        }
        mapped = decision_map.get(decision, {
            # Keep 'Pending' until we review and figure out what is going on
            'status': 'Pending',
            'log_level': logging.ERROR,
            'message': "Unexpected decision from CyberSource regarding {} {} for {} {}. Please investigate ASAP. Redacted response: {}".format(type(request), request.pk, self.customer_type, self.customer_pk, redacted_response)
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
    Base model for all requests we send to CyberSource.
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
        Returns the request_datetime in the format required by CyberSource
        """
        return self.request_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")


class SubscriptionFields(models.Model):
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
    # N.B. the Cybersource test environment returns error codes for certain amounts, by design.
    # The docs are very unclear about the specifics.
    # Try to charge under $1,000 or over $10,000 when testing to avoid.
    amount = models.DecimalField(
        max_digits=19,
        decimal_places=2,
        help_text="Amount to be charged immediately"
    )
    recurring_amount = models.DecimalField(
        max_digits=19,
        decimal_places=2,
        help_text="Amount to be charged repeatedly, beginning on recurring_start_date"
    )
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
    3) comparing notes with CyberSource records
    """
    def __str__(self):
        return 'SubscriptionRequest {}'.format(self.id)

    subscription_agreement = models.OneToOneField(
        SubscriptionAgreement,
        related_name='subscription_request'
    )
    transaction_type = models.CharField(
        max_length=30,
        default='sale,create_payment_token'
    )
    reference_number = models.CharField(
        max_length=32,
        default=generate_reference_number,
        help_text="Unique ID for this subscription. " +
                  "Subsequent charges, automatically made by CyberSource on the recurring schedule, " +
                  "will all be associated with this reference number. " +
                  "Called 'Merchant Reference Number' in CyberSource Business Center."
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
        Returns the recurring_start_date in the format required by CyberSource
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
        related_name='change_requests'
    )
    transaction_type = models.CharField(
        max_length=30,
        default='sale,update_payment_token'
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
    3) comparing notes with CyberSource records
    """
    def __str__(self):
        return 'UpdateRequest {}'.format(self.id)

    subscription_agreement = models.ForeignKey(
        SubscriptionAgreement,
        related_name='update_requests'
    )
    transaction_type = models.CharField(
        max_length=30,
        default='update_payment_token'
    )

    @property
    def customer_pk(self):
        return self.subscription_agreement.customer_pk

    @property
    def customer_type(self):
        return self.subscription_agreement.customer_type


class Response(PolymorphicModel):
    """
    Base model for all responses we receive from CyberSource.

    Most fields are null, just in case CyberSource sends us something ill-formed.
    """
    def __str__(self):
        return 'Response {}'.format(self.id)

    def clean(self, *args, **kwargs):
        super(Response, self).clean(*args, **kwargs)
        if not self.full_response:
            raise ValidationError({'full_response': 'This field cannot be blank.'})

    # we can't guarantee cybersource will send us these fields, though we sure hope so
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
        # It's not like CyberSource will listen for a 400 response, and
        # we should be notified, which will happen automatically if save fails.
        #
        # response.full_clean()
        response.save()


class SubscriptionRequestResponse(Response):
    """
    All (non-confidential) specifics of CyberSource's response to a subscription request.
    """
    def __str__(self):
        return 'SubscriptionRequestResponse {}'.format(self.id)

    related_request = models.OneToOneField(
        SubscriptionRequest,
        related_name='subscription_request_response'
    )
    payment_token = models.CharField(
        max_length=26,
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
    All (non-confidential) specifics of CyberSource's response to a change request.
    """
    def __str__(self):
        return 'ChangeRequestResponse {}'.format(self.id)

    related_request = models.OneToOneField(
        ChangeRequest,
        related_name='change_request_response'
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
    All (non-confidential) specifics of CyberSource's response to an update request.
    """
    def __str__(self):
        return 'UpdateRequestResponse {}'.format(self.id)

    related_request = models.OneToOneField(
        UpdateRequest,
        related_name='update_request_response'
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
