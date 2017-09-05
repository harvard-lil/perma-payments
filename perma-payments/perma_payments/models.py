import random
from uuid import uuid4
from polymorphic.models import PolymorphicModel

from django.conf import settings
from django.db import models

from .security import encrypt_for_storage

import logging
logger = logging.getLogger(__name__)

#
# HELPERS
#


def generate_reference_number():
    """
    Generate a unique, human-friendly reference number. Based on Perma GUID generation.

    Only make 100 attempts:
    If there are requent collisions, expand the keyspace or change the prefix.
    """
    rn_set = "0123456789"
    reference_number_prefix = "PERMA"
    for i in range(100):
        # Generate an 8-character random string like "91276803"
        rn = ''.join(random.choice(rn_set) for _ in range(8))

        # apply standard formatting
        rn = get_canonical_reference_number(rn, reference_number_prefix)

        # see if reference number is unique
        if not SubscriptionRequest.objects.filter(reference_number=rn).exists():
            break
        break
    else:
        raise Exception("No valid reference_number found in 100 attempts.")
    return rn


def get_canonical_reference_number(rn, prefix):
    """
    Given a string of digits, return the canonical version (prefixed and with hyphens every 4 chars).
    E.g "12345678" -> "PERMA-1234-5678".
    """
    # split reference number into 4-char chunks, starting from the end
    rn_parts = [rn[max(i - 4, 0):i] for i in
                range(len(rn), 0, -4)]

    # stick together parts with '-'
    return "{}-{}".format(prefix, "-".join(reversed(rn_parts)))


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

    registrar = models.IntegerField()
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
            ('Cancelled', 'Cancelled'),
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
    status_updated = models.DateTimeField(auto_now=True)
    cancellation_requested = models.BooleanField(
        default=False
    )


    @classmethod
    def registrar_standing_subscription(cls, registrar):
        standing = cls.objects.filter(registrar=registrar, status__in=['Current', 'Hold'])
        count = len(standing)
        if count == 0:
            return None
        if count > 1:
            logger.error("Registrar {} has multiple standing subscriptions ({})".format(registrar, len(count)))
            if settings.RAISE_IF_MULTIPLE_SUBSCRIPTIONS_FOUND:
                raise cls.MultipleObjectsReturned
        return standing.first()


    def can_be_altered(self):
        return self.status in ('Current', 'Hold') and not self.cancellation_requested


class OutgoingTransaction(PolymorphicModel):
    """
    Base model for all requests we send to CyberSource.
    """
    transaction_uuid = models.UUIDField(
        default=uuid4,
        help_text="A unique ID for this 'transaction'. " +
                  "Intended to protect against duplicate transactions."
    )
    request_datetime = models.DateTimeField(auto_now_add=True, null=True)

    def get_formatted_datetime(self):
        """
        Returns the request_datetime in the format required by CyberSource
        """
        return self.request_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")


class SubscriptionRequest(OutgoingTransaction):
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
    reference_number = models.CharField(
        max_length=32,
        default=generate_reference_number,
        help_text="Unqiue ID for this subscription. " +
                  "Subsequent charges, automatically made byCyberSource onthe recurring schedule, " +
                  "will all be associated with this reference number. " +
                  "Called 'Merchant Reference Number' in CyberSource Business Center."
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
    recurring_start_date = models.DateField(
        help_text="Date on which to commence charging recurring_amount"
    )
    recurring_frequency = models.CharField(
        max_length=20,
        choices=(
            ('weekly', 'weekly'),  # every 7 days.
            ('bi-weekly', 'bi-weekly'),  # every 2 weeks.
            ('quad-weekly', 'quad-weekly'),  # every 4 weeks.
            ('monthly', 'monthly'),
            ('semi-monthly', 'semi-monthly'),  # twice every month (1st and 15th).
            ('quarterly', 'quarterly'),
            ('semi-annually', 'semi-annually'),  # twice every year.
            ('annually', 'annually')
        )
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
    transaction_type = models.CharField(
        max_length=30,
        default='sale,create_payment_token'
    )

    @property
    def registrar(self):
        return self.subscription_agreement.registrar


    def get_formatted_start_date(self):
        """
        Returns the recurring_start_date in the format required by CyberSource
        """
        return self.recurring_start_date.strftime("%Y%m%d")


class UpdateRequest(OutgoingTransaction):
    """
    All (non-confidential) specifics of a customer's request to update their payment information.

    Useful for:
    1) reconstructing a customer's account history;
    2) resending failed requests;
    3) comparing notes with CyberSource records
    """
    def __str__(self):
        return 'SubscriptionRequest {}'.format(self.id)

    subscription_agreement = models.ForeignKey(
        SubscriptionAgreement,
        related_name='update_request'
    )
    transaction_type = models.CharField(
        max_length=30,
        default='update_payment_token'
    )

    @property
    def registrar(self):
        return self.subscription_agreement.registrar


class Response(PolymorphicModel):
    """
    Base model for all responses we receive from CyberSource.
    """
    decision = models.CharField(
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
    reason_code = models.IntegerField(null=True)
    message = models.TextField(null=True)
    full_response = models.BinaryField(
        null=True,
        help_text="The full response, encrypted, in case we ever need it."
    )
    encryption_key_id = models.IntegerField(null=True)

    @property
    def subscription_agreement(self):
        """
        Must be implemented by child models
        """
        raise NotImplementedError

    @property
    def registrar(self):
        """
        Must be implemented by child models
        """
        raise NotImplementedError


    @classmethod
    def save_new_w_encryped_full_response(cls, response_class, full_response, fields):
        """
        Saves a new instance of type response_class, encrypting the
        'full_response' field
        """
        data = {
            'encryption_key_id': settings.STORAGE_ENCRYPTION_KEYS['id'],
            'full_response': encrypt_for_storage(
                bytes(str(full_response.dict()), 'utf-8'),
                # use the OutgoingTransaction pk as the nonce, to ensure uniqueness
                (fields['related_request'].pk).to_bytes(24, byteorder='big')
            )
        }
        data.update(fields)
        response = response_class(**data)
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
    def registrar(self):
        return self.related_request.subscription_agreement.registrar


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
    def registrar(self):
        return self.related_request.subscription_agreement.registrar
