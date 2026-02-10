"""
Pytest configuration and shared fixtures for perma_payments tests.
"""
import os

# Allow Django database operations in async context (required for pytest-playwright)
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

from datetime import datetime
from pathlib import Path

import pytest
from unittest.mock import Mock, MagicMock

from django.conf import settings

from perma_payments.security import encrypt_for_perma, stringify_data
from perma_payments.tests import trace as trace_module
from perma_payments.providers.router import get_provider
from perma_payments.providers.tunnels import PROVIDER_PORTS


# =============================================================================
# Pytest Configuration
# =============================================================================

def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--live-sandbox",
        action="store_true",
        default=False,
        help="Run tests that hit live payment provider sandboxes",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "live_sandbox: mark test as requiring live sandbox access (use --live-sandbox to run)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip live_sandbox tests unless --live-sandbox flag is provided."""
    if config.getoption("--live-sandbox"):
        # --live-sandbox given: don't skip live sandbox tests
        return
    
    skip_live = pytest.mark.skip(reason="need --live-sandbox option to run")
    for item in items:
        if "live_sandbox" in item.keywords:
            item.add_marker(skip_live)


def pytest_sessionfinish(session, exitstatus):
    """Generate trace report after all tests have run."""
    traces_dir = Path(__file__).parent / 'traces'
    if traces_dir.exists():
        try:
            report_path = trace_module.generate_report(traces_dir)
            print(f'\nTrace report: {report_path}')
        except Exception as e:
            print(f'\nFailed to generate trace report: {e}')


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Capture browser state when a Playwright test fails.
    
    This hook runs after each test phase (setup, call, teardown).
    If the test fails during the 'call' phase (actual test execution),
    and a page is registered with the trace module, we capture a screenshot.
    """
    outcome = yield
    rep = outcome.get_result()
    
    # Only capture on test failure during the call phase
    if rep.when == "call" and rep.failed:
        # Get the exception info
        if call.excinfo is not None:
            trace_module.capture_failure(call.excinfo.value)


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def clear_content_type_cache(db):
    """
    Clear Django's ContentType cache before each test.
    
    This is essential for polymorphic models (like OutgoingTransaction) when running
    multiple tests with separate test databases. Without this, Django may try to use
    cached content type IDs from a previous test's database, causing foreign key
    violations like:
    
        ForeignKeyViolation: Key (polymorphic_ctype_id)=(9) is not present in table "django_content_type"
    
    The `db` fixture dependency ensures this runs only for tests that use the database.
    """
    from django.contrib.contenttypes.models import ContentType
    ContentType.objects.clear_cache()
    yield
    ContentType.objects.clear_cache()


# =============================================================================
# Live Sandbox Fixtures
# =============================================================================


@pytest.fixture(scope='session')
def _live_servers():
    """Session-scoped storage for per-provider live servers with cleanup."""
    servers = {}
    yield servers
    for server in servers.values():
        server.stop()


@pytest.fixture
def live_server(request, _live_servers):
    """
    Override live_server to use a fixed port per provider.
    
    Servers persist for the session to avoid SO_REUSEADDR issues.
    Each provider gets its own port, so late webhooks from one provider's
    test won't hit another provider's server.
    """
    from pytest_django.live_server_helper import LiveServer
    
    # Get provider_name from test parameters (if parametrized)
    provider_name = None
    if hasattr(request.node, 'callspec'):
        provider_name = request.node.callspec.params.get('provider_name')
    
    # For non-provider tests, use default random port behavior
    if not provider_name or provider_name not in PROVIDER_PORTS:
        server = LiveServer('localhost')
        request.addfinalizer(server.stop)
        return server
    
    # Get or create session-scoped server for this provider
    if provider_name not in _live_servers:
        port = PROVIDER_PORTS[provider_name]
        _live_servers[provider_name] = LiveServer(f'localhost:{port}')
    
    return _live_servers[provider_name]


def _skip_if_tunnel_not_running(provider_name: str):
    """
    Check if the required tunnel is running for a provider, skip with warning if not.
    
    Call this at the start of live sandbox tests to provide a helpful message
    when tunnels aren't set up.
    """
    import warnings
    from perma_payments.providers.tunnels import is_stripe_tunnel_running, is_ngrok_running
    
    if provider_name == 'stripe':
        if not is_stripe_tunnel_running():
            # Check if webhook_secret is configured (tunnel may have been started and settings written)
            if not settings.PAYMENT_PROVIDERS.get('stripe', {}).get('webhook_secret'):
                warnings.warn(
                    "\n\n"
                    "╔══════════════════════════════════════════════════════════════════╗\n"
                    "║  STRIPE TUNNEL NOT RUNNING                                       ║\n"
                    "║                                                                  ║\n"
                    "║  To run Stripe live tests, start the tunnel in another terminal: ║\n"
                    "║                                                                  ║\n"
                    "║    docker compose exec web inv tunnel-stripe                     ║\n"
                    "║                                                                  ║\n"
                    "║  See LIVE_TEST_README.md for more details.                       ║\n"
                    "╚══════════════════════════════════════════════════════════════════╝\n",
                    UserWarning,
                    stacklevel=3
                )
                pytest.skip("Stripe tunnel not running - run 'inv tunnel-stripe' in another terminal")
    
    elif provider_name == 'cybersource_legacy':
        if not is_ngrok_running():
            warnings.warn(
                "\n\n"
                "╔══════════════════════════════════════════════════════════════════╗\n"
                "║  NGROK TUNNEL NOT RUNNING                                        ║\n"
                "║                                                                  ║\n"
                "║  CyberSource Legacy requires ngrok for callbacks.                ║\n"
                "║  Start the tunnel in another terminal:                           ║\n"
                "║                                                                  ║\n"
                "║    docker compose exec web inv tunnel-cybersource-legacy         ║\n"
                "║                                                                  ║\n"
                "║  Then configure the callback URL in CyberSource Business Center. ║\n"
                "║  See LIVE_TEST_README.md for more details.                       ║\n"
                "╚══════════════════════════════════════════════════════════════════╝\n",
                UserWarning,
                stacklevel=3
            )
            pytest.skip("ngrok tunnel not running - run 'inv tunnel-cybersource-legacy' in another terminal")


@pytest.fixture
def require_tunnel():
    """
    Fixture that provides a function to check if required tunnels are running.
    
    Usage:
        def test_something(require_tunnel):
            require_tunnel('stripe')  # Skips with warning if tunnel not running
    """
    return _skip_if_tunnel_not_running


@pytest.fixture
def perma_payload():
    """
    Factory fixture to create encrypted payloads that simulate data from Perma.
    
    Usage:
        payload = perma_payload({
            'customer_pk': 123,
            'customer_type': 'Registrar',
            'amount': '10.00',
            ...
        })
        response = client.post('/subscribe/', {'encrypted_data': payload})
    """
    def _create_payload(data: dict) -> str:
        """
        Create an encrypted payload as Perma would send it.
        
        Adds a fresh timestamp automatically.
        """
        # Add timestamp if not present
        if 'timestamp' not in data:
            data = {**data, 'timestamp': datetime.utcnow().timestamp()}
        
        # Stringify and encrypt
        encrypted = encrypt_for_perma(stringify_data(data))
        
        # Return as string (base64 encoded)
        return encrypted.decode('ascii')
    
    return _create_payload


@pytest.fixture(scope="session")
def available_providers() -> bool:
    """Check if a provider is configured and available for new subscriptions."""
    return [
        provider_name
        for provider_name in settings.PAYMENT_PROVIDERS
        if get_provider(provider_name).can_handle_new_subscription()
    ]


@pytest.fixture
def mock_checkout_provider(mocker):
    """
    Fixture that mocks get_checkout_provider to return a mock provider.
    
    The mock provider's get_*_context methods return (template, context) tuples
    using 'redirect.html' (legacy behavior).
    
    Usage:
        def test_something(client, mock_checkout_provider):
            provider_mock, get_provider_mock = mock_checkout_provider
            # provider_mock is the provider instance
            # get_provider_mock is the patched get_checkout_provider function
    """
    from django.http import HttpResponse
    
    provider_mock = Mock()
    provider_mock.name = 'cybersource_legacy'
    
    # Return a rendered response like the real CyberSource legacy provider
    default_response = HttpResponse('<html><body>Mock checkout page</body></html>')
    provider_mock.checkout_subscribe.return_value = default_response
    provider_mock.checkout_purchase.return_value = default_response
    provider_mock.checkout_change.return_value = default_response
    provider_mock.checkout_update.return_value = default_response
    
    get_provider_mock = mocker.patch(
        'perma_payments.views.get_checkout_provider',
        return_value=provider_mock
    )
    
    # Also mock get_provider for change/update views
    mocker.patch(
        'perma_payments.views.get_provider',
        return_value=provider_mock
    )
    
    return provider_mock, get_provider_mock


@pytest.fixture
def mock_legacy_provider_response():
    """
    Fixture that provides a factory for creating mock HttpResponse objects.
    
    This can be used to customize the response returned by the provider.
    
    Usage:
        def test_something(mock_checkout_provider, mock_legacy_provider_response):
            provider_mock, _ = mock_checkout_provider
            provider_mock.checkout_subscribe.return_value = mock_legacy_provider_response(
                content='<html>Custom content</html>'
            )
    """
    from django.http import HttpResponse
    
    def _create_response(content=None):
        return HttpResponse(content or '<html><body>Mock checkout page</body></html>')
    return _create_response


@pytest.fixture
def mock_stripe_provider(mocker):
    """
    Fixture that mocks get_checkout_provider to return a mock Stripe provider.
    
    Usage:
        def test_stripe_checkout(client, mock_stripe_provider):
            provider_mock, get_provider_mock = mock_stripe_provider
    """
    from django.http import HttpResponseRedirect
    
    provider_mock = Mock()
    provider_mock.name = 'stripe'
    
    # Return redirect response like the real Stripe provider
    default_response = HttpResponseRedirect('https://checkout.stripe.com/xxx')
    provider_mock.checkout_subscribe.return_value = default_response
    provider_mock.checkout_purchase.return_value = default_response
    provider_mock.checkout_change.return_value = default_response
    provider_mock.checkout_update.return_value = default_response
    
    get_provider_mock = mocker.patch(
        'perma_payments.views.get_checkout_provider',
        return_value=provider_mock
    )
    
    return provider_mock, get_provider_mock


@pytest.fixture
def mock_stripe_module(mocker):
    """
    Fixture that mocks the stripe module for testing Stripe provider.
    
    Returns a MagicMock that can be configured with expected responses.
    
    Usage:
        def test_stripe(mock_stripe_module):
            mock_session = MagicMock()
            mock_session.id = 'cs_test_xxx'
            mock_stripe_module.checkout.Session.create.return_value = mock_session
    """
    mock_stripe = MagicMock()
    mocker.patch.dict('sys.modules', {'stripe': mock_stripe})
    return mock_stripe


@pytest.fixture
def trace(request, tmp_path_factory):
    """
    Fixture that provides the trace module for integration test tracing.

    Sets up tracing before the test, yields the trace module for use in the test,
    then calls teardown and generates an HTML report after the test completes.

    The trace files are stored in a 'traces' directory within the pytest tmp directory.
    Files are named after the test: <test_name>.jsonl and <test_name>.html

    For Playwright tests, use `traced_page` fixture instead to get automatic
    failure screenshot capture.

    Usage:
        def test_checkout_flow(trace, client):
            trace.log('User initiates checkout')
            response = client.post('/subscribe/', data={...})
            trace.log(response, label='Subscription response')
            trace.ic(some_variable)  # log with icecream
            # Report is automatically generated after test
    """
    # Create traces directory
    traces_dir = Path(__file__).parent / 'traces'
    traces_dir.mkdir(parents=True, exist_ok=True)

    # Use test node name for the file (sanitized)
    test_name = request.node.name.replace('[', '_').replace(']', '_').replace('/', '_').strip('_')
    output_path = traces_dir / f'{test_name}.jsonl'

    # Setup tracing
    trace_module.setup(output_path)

    yield trace_module

    # Teardown and update manifest
    trace_module.teardown()
    try:
        traces_dir = trace_module.generate_report(traces_dir)
        # Print location so it's visible in test output (None if no meaningful entries)
        if traces_dir:
            print(f'\nTrace: {output_path.name}')
    except FileNotFoundError:
        # No trace entries were written
        pass


@pytest.fixture
def traced_page(trace, page):
    """
    Fixture that combines trace and Playwright page with automatic failure capture.
    
    Registers the page with the trace module so that if the test fails,
    a screenshot is automatically captured showing the browser state at failure time.
    
    Usage:
        def test_checkout_flow(traced_page, live_server):
            trace, page = traced_page
            page.goto(live_server.url + '/subscribe/')
            trace.screenshot(page, title='Checkout page')
            # If test fails, browser state is automatically captured
    
    Returns:
        tuple: (trace_module, page) - both the trace module and the page
    """
    trace_module.register_page(page)
    yield trace, page

