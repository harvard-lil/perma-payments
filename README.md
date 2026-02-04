# perma-payments

[![test status](https://github.com/harvard-lil/perma-payments/actions/workflows/tests.yml/badge.svg)](https://github.com/harvard-lil/perma-payments/actions) [![codecov](https://codecov.io/gh/harvard-lil/perma-payments/branch/develop/graph/badge.svg?token=RnJFtYHFZB)](https://codecov.io/gh/harvard-lil/perma-payments)

1. [The Plot](#the-plot)
2. [Design Notes](#design-notes)
3. [Common Tasks](#common-tasks)
4. [Running Locally](#running-locally)
5. [Testing](#testing)
6. [Migrations](#migrations)
7. [Build for local Perma development](#build-for-local-perma-development)
8. [Running Locally with Perma](#running-locally-with-perma)
9.  [Contributions](#contributions)
10. [License](#license)

The Plot
--------

[Perma.cc](https://github.com/harvard-lil/perma) is rolling out a paid beta for
law firms and other entities that do not qualify for an unlimited free account.


### Payment Providers

Perma Payments supports multiple payment providers:

- **Stripe**: Modern payment processing with Stripe Checkout. Supports automatic
  subscription management and programmatic cancellation.
- **CyberSource REST**: CyberSource REST API with Flex Microform for embedded
  card entry. Supports programmatic subscription management.
- **CyberSource Legacy**: CyberSource Secure Acceptance Web/Mobile (redirect-based).
  Requires manual subscription management via the Business Center.

The active provider is configured in `settings.CHECKOUT_PROVIDERS`. When processing
a new subscription, Perma Payments probes providers in order until finding one with
valid credentials.

Probing multiple is particularly useful during a transition that disables one provider
and enables another, so the new provider can be used as soon as it comes online.


### Subscribing

Perma.cc admins can create registrars and, in the Perma.cc interface, indicate
that the individual registrars may participate in the paid beta. (See the
[Perma docs]() for detailed instructions.) Then, at their leisure, registrar
users associated with those registrars may visit their Perma.cc settings page,
where they will find the option to subscribe/upgrade to a paid account.

When a registrar user indicates they wish to purchase a paid account for their
registrar, Perma POSTS the necessary details to Perma Payments (see
views.subscribe). The communication contains the minimal amount of information
possible: the id of the registrar, and a few details about the desired payment
schedule. No personally identifiable information (PII) or otherwise sensitive
information is included in the POST. However, to ensure that all POSTS indeed
originate from Perma.cc, and for extra protection, all transmitted data is
encrypted.

After processing the POST, Perma Payments routes the user to the configured
payment provider's checkout experience:

- **Stripe**: Redirects to Stripe Checkout, a hosted payment page
- **CyberSource REST**: Renders an embedded Flex Microform for card entry
- **CyberSource Legacy**: Auto-submits a signed form to CyberSource's hosted page

The user enters their payment information and finalizes the transaction
using the provider's systems: payment information never touches Perma Payments or
Perma.cc.

When the transaction is complete, the user is redirected to their Perma.cc
settings page, and Perma Payments is informed of the result via callback/webhook.


### Updating Information

If a subscribed registrar wishes to update their billing information,
they visit their Perma.cc settings page and initiate a request. The update
flow varies by provider:

- **Stripe**: Uses Stripe's Billing Portal for self-service payment updates
- **CyberSource REST/Legacy**: Renders a payment form to update card details


### Cancelling

Subscribed users may indicate they wish to cancel by visiting their Perma.cc
settings page. The cancellation process depends on the provider:

- **Stripe/CyberSource REST**: Cancellation is processed automatically via API.
  Staff receive an informational email confirming the cancellation.
- **CyberSource Legacy**: Does not support programmatic cancellation. Staff are
  notified immediately and must manually cancel in the Business Center.

For providers requiring manual cancellation, staff are sent a daily report of
all pending cancellation requests to ensure no requests go astray.


### Subscription Statuses

In the course of business, Perma.cc needs to know the status of a given
registrar's subscription: do they in fact have a standing subscription?
Is their payment current? etc. (See models.SubscriptionAgreement.status for a
list of all possible subscription statuses and what they mean.)

Perma Payments makes this information available to Perma.cc via a POST-only
api route (see views.subscription). Using the same communication pattern
as already described, Perma.cc POSTS a small amount of encrypted, non-sensitive
data to Perma Payments; Perma Payments verifies the request and POSTs back an
encrypted response.

#### Note on Status Accuracy

Status accuracy varies by provider:

- **Stripe**: Webhook events keep Perma Payments informed of subscription changes
  in real-time (renewals, failures, cancellations).
- **CyberSource REST**: Similar webhook-based status updates.
- **CyberSource Legacy**: Does not expose up-to-date subscription statuses via API.
  Staff should periodically download status reports from the Business Center
  and upload them to Perma Payments. See "Common Tasks" below.


Design Notes
------------

### On Provider Architecture

Perma Payments uses a provider abstraction layer (`perma_payments/providers/`)
that allows different payment providers to implement a common interface. Each
provider handles:
- Checkout flows (subscribe, purchase, change, update)
- Webhook/callback processing
- Credential validation

### On Communicating with Payment Providers

Perma.cc is designed to interact with Perma Payments, and Perma Payments is
designed to interact with payment providers; Perma.cc never communicates with
payment providers directly.

### On Storing Replies from Payment Providers

Perma Payments has no control over which information providers include
in their responses to subscription requests and update requests. Since
providers can and do send back potentially sensitive information,
such as customer billing addresses, Perma Payments does NOT store
responses as-is. Instead, Perma Payments extracts the minimum fields
necessary for business requirements, ALL of which are non-sensitive,
and stores them in its database. For thoroughness, the full response
is encrypted and stored in a form that can only be decrypted using
keys kept offline in secure physical locations.


Common Tasks
------------

### Provider Dashboards

- **Stripe**: [https://dashboard.stripe.com](https://dashboard.stripe.com)
- **CyberSource Business Center (test)**: [https://ebctest.cybersource.com](https://ebctest.cybersource.com/ebctest/login/LoginProcess.do)
- **CyberSource Business Center (prod)**: [https://ebc.cybersource.com](https://ebc.cybersource.com/ebc/login/LoginProcess.do)


### Update Subscription Statuses (CyberSource Legacy only)

For CyberSource Legacy subscriptions, status updates must be done manually:

1) Go to [https://ebctest.cybersource.com/ebc2/app/VirtualTerminal/RecurringBilling](https://ebctest.cybersource.com/ebc2/app/VirtualTerminal/RecurringBilling) (the test Business Center) or [https://ebc.cybersource.com/ebc2/app/VirtualTerminal/RecurringBilling](https://ebc.cybersource.com/ebc2/app/VirtualTerminal/RecurringBilling) (the production Business Center).

2) In the Subscription List header, next to the "New Subscription" button, there is a download button (visually, an underlined arrow). Click it, and then select CSV. (Don't worry about pagination, unlike with previous versions of CyberSource's software.)

3) Log in to the Perma Payments admin.

4) Upload the CSV to the "Update Subscription Statuses" form. Submit.

5) *Important* Safety check: review the list of subscriptions in the Perma Payments admin, and verify that everything looks good, especially that subscription statuses look correct, and that there's nothing weird in the subscriptions filter. (CyberSource recently broke the spreadsheet we use, and this is how we found out.)

Et voilà.


Running Locally
--------------

### Spin up some containers

Start up the Docker containers in the background:

    $ docker compose up -d

The first time this runs it will build the Docker images, which
may take several minutes. (After the first time, it should only take
1-3 seconds.)

Then log into the main Docker container:

    $ docker compose exec web bash

(Commands from here on out that start with `#` are being run in Docker.)

### Run Django

You should now have a working installation!

Spin up the development server:

    # invoke run

### Stop

When you are finished, spin down Docker containers by running:

    $ docker compose down

Your database will persist and will load automatically the next time you run `docker compose up -d`.


Testing
-------

### Test Commands

1. `# invoke test` runs python tests
1. `# flake8` runs python lints

### Coverage

Coverage will be generated automatically for all manually-run tests.


Migrations
-------
We use standard Django migrations


Build for local Perma development
-------
Replacing `0.0` with the correct tag, run:
```
docker build -t harvardlil/perma-payments:0.0  -f ./docker/Dockerfile .
```

Running Locally with Perma
--------------

If you want to work on a feature that spans Perma Payments and Perma, you can run Perma Payments locally on the same network as Perma.

With no other Docker containers running (`docker ps` returns no results), start the Perma Payments containers (`docker compose up -d`) and run the development server (`docker compose exec web invoke run)/`). Then, head over to the [`perma` repo](https://github.com/harvard-lil/perma/blob/develop/developer.md#test-perma-interaction-with-perma-payments) to run instructions on how to start up Perma so that it talks to this already-running instance of Perma Payments rather than spinning up its own as usual.

Contributions
-------
Contributions to this project should be made in individual forks and then merged by pull request. Here's an outline:

1. Fork and clone the project.
2. Make a branch for your feature: `git branch feature-1`
3. Commit your changes with `git add` and `git commit`. (`git diff  --staged` is handy here!)
4. Push your branch to your fork: `git push origin feature-1`
5. Submit a pull request to the upstream develop through GitHub.


License
-------
This codebase is Copyright 2020 The President and Fellows of Harvard College and is licensed under the open-source AGPLv3 for public use and modification. See [LICENSE](LICENSE) for details.
