import random
from uuid import uuid4

from django.db import models

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
        related_name='subscription_agreement'
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


class SubscriptionRequestResponse():
    pass
    # subscription_request = models.OneToOneField(
    #     SubscriptionRequest,
    #     related_name='subscription_request'
    # )

    # Response

    # signature=/QQFU5A0wzol7F8zmTrbwJHUti1QlZDCL9Y5o918yYw=
    # signed_field_names=transaction_id,decision,req_access_key,req_profile_id,req_transaction_uuid,req_transaction_type,req_reference_number,req_amount,req_currency,req_locale,req_payment_method,req_recurring_frequency,req_recurring_amount,req_bill_to_forename,req_bill_to_surname,req_bill_to_email,req_bill_to_address_line1,req_bill_to_address_city,req_bill_to_address_state,req_bill_to_address_country,req_bill_to_address_postal_code,req_card_number,req_card_type,req_card_expiry_date,message,reason_code,auth_avs_code,auth_avs_code_raw,auth_response,auth_amount,auth_code,auth_trans_ref_no,auth_time,request_token,bill_trans_ref_no,payment_token,signed_field_names,signed_date_time
    # signed_date_time=2017-07-10T19:18:10Z

    # transaction_id=4997142906156171104101
    # payment_token=4997142906156171104101
    # decision=ACCEPT
    # message=Request was processed successfully.
    # reason_code=100

    # auth_trans_ref_no=74891332D4XYOO7T
    # auth_amount=1.00
    # auth_response=100
    # auth_time=2017-07-10T191810Z
    # auth_avs_code_raw=I1 String (1)
    # auth_avs_code=X
    # auth_code=888888

    # bill_trans_ref_no=74891332D4XYOO7T

    # request_token=Ahj//wSTDuVJ9Sa1v49lESDdo4csWbNlEaWLM+e3qJb374OagClvfvg5qaQHyOC8MmkmXoxXF8ZBgTkw7lSfUmtb+PZQyxrh

    # req_transaction_uuid=04e2347d-8e5d-4ec9-a819-74c3258f4a9f
    # req_reference_number=PERMA-6782-9670

    # req_recurring_frequency=monthly
    # req_card_number=xxxxxxxxxxxx1111
    # req_locale=en-us
    # req_bill_to_surname=name
    # req_bill_to_address_city=Mountain View
    # req_card_expiry_date=12-2022
    # req_bill_to_address_postal_code=94043
    # req_bill_to_forename=noreal
    # req_payment_method=card
    # req_recurring_amount=1.00
    # req_amount=1.00
    # req_bill_to_email=null@cybersource.com
    # req_bill_to_address_country=US
    # req_transaction_type=sale,create_payment_token
    # req_access_key=7e6a19738a913a45aedc6c6abdda3998
    # req_profile_id=2C5AD95B-B3EC-4F59-9138-32910CEB6A69
    # req_bill_to_address_state=CA
    # req_bill_to_address_line1=1295 Charleston Road
    # req_currency=USD
    # req_card_type=001
