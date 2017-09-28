# perma-payments

[![Build Status](https://travis-ci.org/harvard-lil/perma-payments.svg?branch=develop)](https://travis-ci.org/harvard-lil/perma-payments) [![Coverage Status](https://coveralls.io/repos/github/harvard-lil/perma-payments/badge.svg?branch=develop)](https://coveralls.io/github/harvard-lil/perma-payments?branch=develop)

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
that the individual registrars may particate in the paid beta. (See the
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
regsitrar's subscription: do they in fact have a standing subscription?
Is their payment current? etc.

Perma Payments makes this information available to Perma.cc via a POST-only
api route (see views.subscription). Using the same communication pattern
as already described, Perma.cc POSTS a small amount of encrypted, non-sensitive
data to Perma Payments; Perma Payments verifies the request and POSTs back an
encrypted response.

#### Note on Status Accuracy

CyberSource does not expose subscription status via an easily-accessible
API. This has two potential consequences for Perma.cc/Perma Payments:

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
  update subscription statuses via CSV upload. See "How To" below for
  detailed instructions.

  Monthly subscriptions are renewed on the first of the month; updating
  statuses on the 2nd of the month and after any cancellation request
  should be sufficient.


Design Notes
------------

### On Customizing CyberSource

Whenever possible, Perma Payments makes use of CyberSource features, rather
than implementing custom functionality. For example, at this time, we are
using CyberSource's own "Response Pages", rather than custom built pages.
If further customization is required in the future, we can consider:
- embedding the CyberSource checkout page in an iframe whose wrapper is
hosted at Perma Payments
- building custom repsonse pages, hosted at Perma.cc or Perma Payments

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
prod: (coming soon)


### Update Subscription Statuses

1) Go to [https://ebctest.cybersource.com/ebctest/subscriptions/SubscriptionSearchExecute.do](https://ebctest.cybersource.com/ebctest/subscriptions/SubscriptionSearchExecute.do) (the test Business Center) or [https://ebctest.cybersource.com/ebctest/subscriptions/SubscriptionSearchExecute.do](https://ebctest.cybersource.com/ebctest/subscriptions/SubscriptionSearchExecute.do) (the production Business Center).

2) Verify that you can see all the subscriptions. (If there are no pagination buttons, then you can see all the subscriptions.)

3) Scroll to the bottom of the page and click the "Export CSV" button.

4) Log in to the Perma Payments admin.

5) Upload the CSV to the "Update Subscription Statuses" form. Submit.

Et voilà.


Runnng Locally
--------------

## Up

1. Install [Docker](https://docs.docker.com/installation/) or [Docker Toolbox](https://www.docker.com/products/docker-toolbox)

2. `git clone https://github.com/harvard-lil/perma-payments.git`

3. `cd perma-payments`

4. (recommended) Nickname some commonly-used commands by adding the following to your .bash_profile or similar:
`alias dfab="docker-compose exec web fab"`
`alias dmanage.py="docker-compose exec web manage.py"`

5. Run `docker-compose up -d` to start two containers in the background:
    -  a "db" container with a postgres database
    -  a "web" container with python, Django, and the rest of our dev environment.

6. Run `dfab init_dev_db` to initialize a development database.

7. Run `dfab run` to start the Django development server.

8. Navigate to perma-payments:
   -  Docker: head to http://localhost/
   -  Docker Machine: run `docker-machine ip` to discover the IP address of your virtualbox. Then, head to http://that-ip-address.


## Down

To stop all running containers (and retain any information in your database), run `docker-compose stop`.

To stop and destroy all containers created via docker-compose up, run `docker-compose down`. Note that this will destroy your database and all its data.


## Other helpful commands

To get to a bash terminal in the running docker container, run `docker-compose exec web bash`.

To access the Django shell, `dmanage.py shell`.

To run make and run migrations, `dmanage.py makemigrations; dmanage.py migrate`

To add new python dependencies to an existing image:
  - `docker-compose exec web pip install <package>` to install a new package
  - `docker-compose exec web pip-compile` to recompile requirements.txt from requirements.in
  - `docker-compose exec web pip-sync` to rebuild the virtualenv from requirements.txt

To run the tests, `dfab test`.


## Updating the Docker image

If you change the Dockerfile or commit changes to requirements.txt,
you should increment the tag for perma-payments in docker-compose.yml.
This ensures that an automatic rebuild is triggered for all users, when
they pull in your changes.

To experiment with new builds locally without incrementing the image tag
(which creates a new image on your machine, rather than replacing the old
one, thus using up disk space), run `docker-compose build` or
`docker-compose up -d --build`.

Periodically, you might want to run `docker images` to see if you have
accumulated a lot of cruft.
