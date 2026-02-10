# set up Django
from functools import wraps
import os
import subprocess
import sys

import django

from invoke import task

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

@task
def pip_compile(ctx, args=''):
    # run pip-compile
    # Use --allow-unsafe because pip --require-hashes needs all requirements to be pinned, including those like
    # setuptools that pip-compile leaves out by default.
    command = ['pip-compile', '--generate-hashes', '--allow-unsafe']+args.split()
    print("Calling %s" % " ".join(command))
    subprocess.check_call(command, env=dict(os.environ, CUSTOM_COMPILE_COMMAND='invoke pip-compile'))


@task
def run(ctx, port=None):  # pragma: no cover
    if port is None:
        port = "0.0.0.0:80" if os.environ.get('DOCKERIZED') else "127.0.0.1:80"
    ctx.run(f'python manage.py runserver {port}')


@task
def test(ctx, ci=False):
    # with Invoke, boolean arguments are switches, and don't have to be considered strings,
    # as in Fabric3; that is, to run tests in CI, use `invoke test --ci`
    # see https://docs.pyinvoke.org/en/stable/concepts/invoking-tasks.html#type-casting
    if ci:
        ctx.run("pytest --ds=config.settings.settings_testing --junitxml=junit/pytest/test-results.xml --fail-on-template-vars --cov --cov-config=setup.cfg --cov-report xml")
    else:
        ctx.run("pytest --ds=config.settings.settings_testing --fail-on-template-vars --cov --cov-report= ")


@task
@setup_django
def init_dev_db(ctx):
    """
    Set up a new dev database.
    """
    ctx.run("python3 manage.py migrate")
    print("Creating dev admin user.")
    from django.contrib.auth.models import User #noqa
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')


@task
@setup_django
def find_pending_cancellation_requests(ctx, tier='dev'):
    """
    Report pending cancellation requests.
    """
    from perma_payments.email import send_self_email  #noqa
    from perma_payments.models import SubscriptionAgreement  #noqa
    from perma_payments.providers.router import get_provider  #noqa
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
        data = []
        for sa in sas:
            provider = get_provider(sa.payment_provider)
            data.append({
                'customer_pk': sa.customer_pk,
                'customer_type': sa.customer_type,
                'merchant_reference_number': sa.subscription_request.reference_number,
                'status': sa.status,
                'payment_provider': sa.payment_provider,
                'manual_cancellation_url': provider.manual_cancellation_url,
            })
        send_self_email(
            'ACTION REQUIRED: cancellation requests pending on %s' % tier,
            RequestFactory().get('this-is-a-placeholder-request'),
            template="email/cancellation_report.txt",
            context={
                'perma_url': settings.PERMA_URL,
                'individual_detail_path': settings.INDIVIDUAL_DETAIL_PATH,
                'registrar_detail_path': settings.REGISTRAR_DETAIL_PATH,
                'registrar_users_path': settings.REGISTRAR_USERS_PATH,
                'total': len(data),
                'requests': data
            },
            devs_only=False
        )


### Tunnel Tasks for Live Sandbox Testing ###

@task
@setup_django
def tunnel_stripe(ctx, forward_to=None):
    """
    Start Stripe CLI webhook forwarding for live sandbox testing.
    
    This runs `stripe listen` to forward webhooks to the local test server,
    extracts the webhook signing secret, and writes it to settings_tunnels.py.
    
    Usage:
        inv tunnel-stripe
        
    The command will run until interrupted (Ctrl+C).
    Make sure you're authenticated: `stripe login`
    """
    from perma_payments.providers.tunnels import StripeTunnel
    
    tunnel = StripeTunnel(forward_to=forward_to)
    tunnel.start()
    tunnel.stream_output()


@task
@setup_django
def tunnel_cybersource_legacy(ctx, port=None):
    """
    Start ngrok tunnel for CyberSource Legacy live sandbox testing.
    
    This exposes the local test server via ngrok so CyberSource can
    send server-to-server callbacks.
    
    Usage:
        inv tunnel-cybersource-legacy
        
    After starting, configure the callback URL in CyberSource Business Center:
        https://YOUR-SUBDOMAIN.ngrok.io/cybersource-callback/
    
    The command will run until interrupted (Ctrl+C).
    """
    from perma_payments.providers.tunnels import NgrokTunnel
    
    tunnel = NgrokTunnel(port=port)
    tunnel.start()
    tunnel.stream_output()


@task
@setup_django
def tunnel_all(ctx):
    """
    Start both Stripe and ngrok tunnels for full live sandbox testing.
    
    Usage:
        inv tunnel-all
        
    This starts both tunnels concurrently and merges their output.
    Press Ctrl+C to stop both.
    """
    from perma_payments.providers.tunnels import StripeTunnel, NgrokTunnel, TunnelGroup
    
    TunnelGroup(StripeTunnel(), NgrokTunnel()).start().wait()
