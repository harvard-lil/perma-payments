# perma-payments

## The plan

Infrastructure
- A Django 1.11 application
- Using Python 3.6.1
- Using a postgres database
- Hosted wherever/however is easiest for compliance, but preferably on AWS
- Developed locally however suits; not in the Perma vagrant box

The app and its relationship with Perma
- Communicates via ssl with perma.cc via a JSON api
- Uses pynacl to sign communications with perma.cc: https://pynacl.readthedocs.io/en/latest/signing/
- If/when needed, stores info in encrypted session cookies
- Has the Django admin enabled during development for our convenience, but disabled in production. (If it turns out to be necessary/convenient, we can set up something for local use on one's laptop that is hooked up to the production database.)
- Doesn't have a concept of "users" (except insofar as to enable the Django admin for development, as per above)
- Whenever possible, passes users to perma.cc or to CyberSource for views, rather than returning a polished response to the user itself
- Whenever possible, outsources business logic to perma.cc (for example, does not attempt to see whether users have exceeded their monthly allotment)
- Retains the minimum subscription/transaction information necessary for compliance in its database; does not store user data (name, address, email address, etc.); associates transactions/subscriptions with a perma user id (or org id, or registrar id... TBD depending on pricing model) for easy retrieval (perma.cc will not itself store a record of transactions/subscription keys)

Communication with CyberSource
- passes the user to CyberSource via a redirect
(more to come here)
