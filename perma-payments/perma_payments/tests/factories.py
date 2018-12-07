import factory
from faker import Faker

import django.utils.timezone

from perma_payments.constants import CS_DECISIONS
from perma_payments.models import (CUSTOMER_TYPES, SubscriptionAgreement,
    SubscriptionRequest, SubscriptionRequestResponse, UpdateRequest,
    UpdateRequestResponse, ChangeRequest)


fake = Faker()

class SubscriptionAgreementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SubscriptionAgreement

    customer_pk = factory.Sequence(lambda n: n)
    customer_type = fake.random_element(elements=CUSTOMER_TYPES),
    status = 'Pending'


class SubscriptionRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SubscriptionRequest

    subscription_agreement = factory.SubFactory(SubscriptionAgreementFactory)

    amount = factory.Faker('pydecimal', left_digits=6, right_digits=2, positive=True)
    recurring_amount = factory.Faker('pydecimal', left_digits=6, right_digits=2, positive=True)
    recurring_start_date = factory.Faker('future_date')
    recurring_frequency = 'monthly'
    link_limit = str(fake.random_element(elements=(fake.random_int(), 'unlimited')))
    link_limit_effective_timestamp = django.utils.timezone.now()


class ChangeRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChangeRequest

    subscription_agreement = factory.SubFactory(
        SubscriptionAgreementFactory,
        subscription_request=factory.SubFactory(SubscriptionRequestFactory)
    )

    amount = factory.Faker('pydecimal', left_digits=6, right_digits=2, positive=True)
    recurring_amount = factory.Faker('pydecimal', left_digits=6, right_digits=2, positive=True)
    link_limit = str(fake.random_element(elements=(fake.random_int(), 'unlimited')))
    link_limit_effective_timestamp = django.utils.timezone.now()


class UpdateRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UpdateRequest

    subscription_agreement = factory.SubFactory(
        SubscriptionAgreementFactory,
        subscription_request=factory.SubFactory(SubscriptionRequestFactory)
    )


class SubscriptionRequestResponseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SubscriptionRequestResponse

    related_request = factory.SubFactory(SubscriptionRequestFactory)

    decision = factory.Iterator(key for key in CS_DECISIONS)
    reason_code = factory.Faker('random_int')
    message = factory.Faker('sentence', nb_words=7)
    full_response = b''
    encryption_key_id = factory.Faker('random_int')
    payment_token = factory.Faker('password', length=26)


class UpdateRequestResponseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UpdateRequestResponse

    related_request = factory.SubFactory(UpdateRequestFactory)
    decision = factory.Iterator(key for key in CS_DECISIONS)
    reason_code = factory.Faker('random_int')
    message = factory.Faker('sentence', nb_words=7)
    full_response = b''
    encryption_key_id = factory.Faker('random_int')

