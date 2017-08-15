import random
from uuid import uuid4

from django.db import models

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
        c) Any subsequent updates from CyberSource about scheduled payments
           associated with the Subscription ID. Indicates whether the agreement
           still stands.

    If any of the values from the initial request are updated (the schedule, the card, the address, etc.)
    the Subscription Agreement becomes obsolete ("superseded") and is replaced by
    an entirely new Subscription Agreement, with a new Payment Token/Subscription ID.

    This is a feature of CyberSource; it is not a perma-payments design decision.
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
            ('Superseded', 'Superseded')
        )
    )
    status_updated = models.DateTimeField(auto_now=True)
    cancellation_requested = models.BooleanField(
        default=False
    )


    @classmethod
    def registrar_has_current(cls, registrar):
        current = cls.objects.filter(registrar=registrar, status='Current').count()
        if current > 1:
            logger.error("Registrar {} has multiple current subscriptions ({})".format(registrar, current))
        return bool(current)


    @classmethod
    def get_registrar_latest(cls, registrar):
        """
        Returns the most recently created Subscription Agreement for a registrar,
        if any exist, or None.
        """
        try:
            sa = cls.objects.filter(registrar=registrar).latest('id')
        except cls.DoesNotExist:
            sa = None
        return sa


    def can_be_cancelled(self):
        return self.status in ('Current', 'Hold') and not self.cancellation_requested


class SubscriptionRequest(models.Model):
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
    transaction_uuid = models.UUIDField(
        default=uuid4,
        help_text="A unique ID for this 'transaction'. " +
                  "Intended to protect against duplicate transactions."
    )
    request_datetime = models.DateTimeField(auto_now_add=True)
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
    # recurring_start_date = models.DateField(
    #     help_text="Date on which to commence charging recurring_amount"
    # )
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

    def get_formatted_datetime(self):
        """
        Returns the request_datetime in the format required by CyberSource
        """
        return self.request_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")


class SubscriptionRequestResponse(models.Model):
    """
    All (non-confidential) specifics of CyberSource's response to a subscription request.
    """
    def __str__(self):
        return 'SubscriptionRequestResponse {}'.format(self.id)

    subscription_request = models.OneToOneField(
        SubscriptionRequest,
        related_name='subscription_request_response'
    )
    decision = models.CharField(
        max_length=7,
        choices=(
            ('ACCEPT', 'ACCEPT'),
            ('REVIEW', 'REVIEW'),
            ('DECLINE', 'DECLINE'),
            ('ERROR', 'ERROR'),
            ('CANCEL', 'CANCEL'),
        )
    )
    reason_code = models.IntegerField()
    message = models.TextField()
    payment_token = models.CharField(
        max_length=26,
        blank=True,
        default=''
    )
    full_response = models.BinaryField(
        help_text="The full response, encrypted, in case we ever need it."
    )
    encryption_key_id = models.IntegerField()
