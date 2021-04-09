# perma-payments

[![harvard-lil](https://circleci.com/gh/harvard-lil/perma-payments.svg?style=svg)](https://github.com/harvard-lil/perma-payments) [![codecov](https://codecov.io/gh/harvard-lil/perma-payments/branch/develop/graph/badge.svg?token=RnJFtYHFZB)](https://codecov.io/gh/harvard-lil/perma-payments)

1. [The Plot](#the-plot)
2. [Common Tasks](#common-tasks)
3. [Design Notes](#design-notes)
3. [Running Locally](#running-locally)


The Plot
--------

[Perma.cc](https://github.com/harvard-lil/perma) is rolling out a paid beta for
law firms and other entities that do not qualify for an unlimited free account.


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

After processing the POST, Perma Payments delivers the user at a page
with a hidden form containing all the information required to communicate
with CyberSource Secure Acceptance Web/Mobile, a payment management platform
(see templates/redirect.html). Again, no PII or otherwise sensitive information
is included; however, the data is signed as per CyberSource requirements. If the
user has Javascript enabled, the form auto-submits, "redirecting" the user to the
CyberSource checkout page. If the form fails to auto-submit for any reason, the
user is presented with a link they can click, to the same effect.

The user enters their payment information and finalizes the transaction
using CyberSource's systems: payment information never touches Perma Payments or
Perma.cc.

When the transaction is complete, the user is redirected to their Perma.cc
settings page (via a setting in the CyberSource Secure Acceptance Web/Mobile
profile), and Perma Payments is informed of the result of the transaction
(see views.cybersource_callback).


### Updating Information

If a subscribed registrar wishes to update their billing information,
they visit their Perma.cc settings page and initiate a request. Just as
with their original subscription request, a POST of encrypted, non-sensitive
data is sent to Perma Payments (see views.update), and the user is delivered at
a page with a self-submitting form that "redirects" them to CyberSource Secure Acceptance Web/Mobile, where they may update their billing information. Perma
Payments informed of the result of the transaction (see views.cybersource_callback).


### Cancelling

CyberSource Secure Acceptance Web/Mobile does not provide a programmatic
way to cancel a subscription.

Subscribed users may indicate they wish to cancel by visiting their Perma.cc
settings page. Just as with their original subscription request, a POST of
encrypted, non-sensitive data is sent to Perma Payments. Perma Payments
records the request and informs Perma.cc staff. Staff are notified of
the request immediately, and are additionally sent a daily report of all
pending cancellation requests, to ensure no requests go astray.

Staff may then cancel the subscription in the CyberSource Business Center,
following the instructions in the notification email sent by Perma Payments.


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

CyberSource does not expose up-to-date subscription statuses via an
easily-accessible API. This has two potential consequences for
Perma.cc/Perma Payments:

1. If a customer successfully signs up for a recurring paid subscription
in CyberSource Secure Acceptance Web/Mobile, and CyberSource's response
to Perma Payments goes astray, Perma Payments will continue to treat the
subscription request as 'pending'.

  In the unlikely evident this occurs, a Perma.cc staff member can manually
  update Perma Payments records when contacted by the affected customer
  (who will be unable to create links).

2. If a customer with a monthly subscription has credit card trouble on
a given month and their subscription lapses, Perma Payments will not
automatically be notified. They will continue to be able to create links.

  To protect against this possibility, Perma.cc staff should periodically
  retrieve up-to-date subscription statuses from CyberSource and update
  Perma Payment's records. This is a quick and easy job; see "Common Tasks"
  below for detailed instructions.

  Since customers with monthly subscriptions are charged on the first of
  every month, updating subscription statuses in Perma Payments on the
  2nd of the month and after any cancellation request should be sufficient.


Design Notes
------------

### On Customizing CyberSource

Whenever possible, Perma Payments makes use of CyberSource features, rather
than implementing custom functionality. For example, at this time, we are
using CyberSource's own "Response Pages", rather than custom built pages.
If further customization is required in the future, we can consider:
- embedding the CyberSource checkout page in an iframe whose wrapper is
hosted at Perma Payments
- building custom response pages, hosted at Perma.cc or Perma Payments

### On Communicating with CyberSource

Perma.cc is designed to interact with Perma Payments, and Perma Payments is
designed to interact with CyberSource; Perma.cc never communicates with
CyberSource.

### On Storing Replies from CyberSource

Perma Payments has no control over which information CyberSource includes
in its responses to subscription requests and update requests. Since
CyberSource can and does send back potentially sensitive information,
such as customer billing addresses, Perma Payments does NOT store
responses from CyberSource as-is. Instead, Perma Payments extracts
the minimum fields necessary for business requirements, ALL of which
are non-sensitive, and stores them in its database. For thoroughness,
the request in its entirety is then encrypted and stored in a form that
can only be decrypted using keys kept offline in secure physical
locations.


Common Tasks
------------

### Log in to the CyberSource Business Center

test: [https://ebctest.cybersource.com/ebctest/login/LoginProcess.do](https://ebctest.cybersource.com/ebctest/login/LoginProcess.do)
prod: [https://ebc.cybersource.com/ebc/login/LoginProcess.do](https://ebc.cybersource.com/ebc/login/LoginProcess.do)


### Update Subscription Statuses

1) Go to [https://ebctest.cybersource.com/ebc2/app/VirtualTerminal/RecurringBilling](https://ebctest.cybersource.com/ebc2/app/VirtualTerminal/RecurringBilling) (the test Business Center) or [https://ebc.cybersource.com/ebc2/app/VirtualTerminal/RecurringBilling](https://ebc.cybersource.com/ebc2/app/VirtualTerminal/RecurringBilling) (the production Business Center).

2) In the Subscription List header, next to the "New Subscription" button, there is a download button (visually, an underlined arrow). Click it, and then select CSV. (Don't worry about pagination, unlike with previous versions of CyberSource's software.)

3) Log in to the Perma Payments admin.

4) Upload the CSV to the "Update Subscription Statuses" form. Submit.

5) *Important* Safety check: review the list of subscriptions in the Perma Payments admin, and verify that everything looks good, especially that subscription statuses look correct, and that there's nothing weird in the subscriptions filter. (Cybersource recently broke the spreadsheet we use, and this is how we found out.)

Et voilà.


Running Locally
--------------

### Spin up some containers

Start up the Docker containers in the background:

    $ docker-compose up -d

The first time this runs it will build the Docker images, which
may take several minutes. (After the first time, it should only take
1-3 seconds.)

Then log into the main Docker container:

    $ docker-compose exec web bash

(Commands from here on out that start with `#` are being run in Docker.)

### Run Django

You should now have a working installation!

Spin up the development server:

    # fab run

### Stop

When you are finished, spin down Docker containers by running:

    $ docker-compose down

Your database will persist and will load automatically the next time you run `docker-compose up -d`.


Testing
-------

### Test Commands

1. `# fab test` runs python tests
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

Contributions
-------
Contributions to this project should be made in individual forks and then merged by pull request. Here's an outline:

1. Fork and clone the project.
1. Make a branch for your feature: `git branch feature-1`
1. Commit your changes with `git add` and `git commit`. (`git diff  --staged` is handy here!)
1. Push your branch to your fork: `git push origin feature-1`
1. Submit a pull request to the upstream develop through GitHub.


License
-------
This codebase is Copyright 2020 The President and Fellows of Harvard College and is licensed under the open-source AGPLv3 for public use and modification. See [LICENSE](LICENSE) for details.
