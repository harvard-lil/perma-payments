# set up Django
from functools import wraps
import os
import subprocess
import sys

import django

from fabric.api import local
from fabric.decorators import task

### Helpers ###

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
_django_setup = False
def setup_django(func):  # pragma: no cover
    """
        For speed, avoid setting up django until we need it. Attach @setup_django to any tasks that rely on importing django packages.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        global _django_setup
        if not _django_setup:
            sys.path.insert(0, '')
            django.setup()
            _django_setup = True
        return func(*args, **kwargs)
    return wrapper


### Tasks ###

@task(alias='pip-compile')
def pip_compile(args=''):
    # run pip-compile
    # Use --allow-unsafe because pip --require-hashes needs all requirements to be pinned, including those like
    # setuptools that pip-compile leaves out by default.
    command = ['pip-compile', '--generate-hashes', '--allow-unsafe']+args.split()
    print("Calling %s" % " ".join(command))
    subprocess.check_call(command, env=dict(os.environ, CUSTOM_COMPILE_COMMAND='fab pip-compile'))


@task(alias='run')
def run_django(port=None):  # pragma: no cover
    if port is None:
        port = "0.0.0.0:80" if os.environ.get('DOCKERIZED') else "127.0.0.1:80"
    local(f'python manage.py runserver {port}')


@task
def test(travis=False):
    # NB: all arguments to Fabric tasks are interpreted as strings
    if travis == 'True':
        local("pytest --ds=config.settings.settings_travis --fail-on-template-vars --cov --cov-report= ")
    else:
        local("pytest --ds=config.settings.settings_testing --fail-on-template-vars --cov --cov-report= ")


@task
@setup_django
def init_dev_db():
    """
    Set up a new dev database.
    """
    local("python3 manage.py migrate")
    print("Creating dev admin user.")
    from django.contrib.auth.models import User #noqa
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')


@task
@setup_django
def find_pending_cancellation_requests(tier='dev'):
    """
    Report pending cancellation requests.
    """
    from perma_payments.constants import CS_SUBSCRIPTION_SEARCH_URL  #noqa
    from perma_payments.email import send_self_email  #noqa
    from perma_payments.models import SubscriptionAgreement  #noqa
    from django.test.client import RequestFactory  #noqa
    from django.conf import settings  #noqa

    sas = SubscriptionAgreement.objects.filter(cancellation_requested=True).exclude(status='Canceled')
    if len(sas) == 0:
        send_self_email(
            'No cancellation requests pending on %s' % tier,
            RequestFactory().get('this-is-a-placeholder-request'),
            context={
                'message': "Congrats, no cancellation requests pending today. ~ Perma Payments"
            }
        )
    else:
        data = [
            {
                'customer_pk': sa.customer_pk,
                'customer_type': sa.customer_type,
                'merchant_reference_number': sa.subscription_request.reference_number,
                'status': sa.status
            } for sa in sas
        ]
        send_self_email(
            'ACTION REQUIRED: cancellation requests pending on %s' % tier,
            RequestFactory().get('this-is-a-placeholder-request'),
            template="email/cancellation_report.txt",
            context={
                'search_url': CS_SUBSCRIPTION_SEARCH_URL[settings.CS_MODE],
                'perma_url': settings.PERMA_URL,
                'individual_detail_path': settings.INDIVIDUAL_DETAIL_PATH,
                'registrar_detail_path': settings.REGISTRAR_DETAIL_PATH,
                'registrar_users_path': settings.REGISTRAR_USERS_PATH,
                'total': len(data),
                'requests': data
            },
            devs_only=False
        )
