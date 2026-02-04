# Live Sandbox Integration Tests

These tests run end-to-end payment flows against real payment provider sandboxes (test environments). They exercise the complete payment lifecycle including browser interactions, API calls, and webhooks.

The tests generate sequence diagrams in the `web/perma_payments/tests/traces/` directory that are useful
for understanding app flows.

## What These Tests Cover

### Test Flows

| Test | Description |
|------|-------------|
| `test_purchase_flow` | One-time purchase: submit payment request → complete checkout → verify completion |
| `test_subscription_lifecycle` | Chained subscription operations: Subscribe → Change → Update Payment → Cancel |

## Running the Tests

### Prerequisites

1. Docker and docker-compose installed
2. Payment provider sandbox credentials configured in `web/config/settings/settings.py`
3. For Stripe tests: Stripe CLI authenticated (see below)

### Basic Usage

```bash
# Run all live sandbox tests
docker compose exec web pytest perma_payments/tests/test_live_sandbox.py --live-sandbox -v

# Run tests for a specific provider
docker compose exec web pytest perma_payments/tests/test_live_sandbox.py --live-sandbox -v -k "cybersource_rest"

# Run a specific test
docker compose exec web pytest perma_payments/tests/test_live_sandbox.py --live-sandbox -v -k "test_purchase_flow[chromium-cybersource_rest]"

# Skip Stripe tests (if CLI not authenticated)
docker compose exec web pytest perma_payments/tests/test_live_sandbox.py --live-sandbox -v -k "not stripe"
```

### Viewing Results

After tests run, trace reports are generated:

```
web/perma_payments/tests/traces/
├── index.html                                    # Index of all test traces
├── test_purchase_flow_chromium-cybersource_rest.html
├── test_purchase_flow_chromium-cybersource_rest.jsonl
├── test_subscription_lifecycle_chromium-cybersource_rest.html
├── ...
└── images/
    └── screenshot_*.png                          # Screenshots from test runs
```

Open `index.html` in a browser to see all test traces, or open individual `.html` files for specific tests.

## Required Settings

Configure sandbox credentials in `web/config/settings/settings.py`:

### CyberSource REST

```python
PAYMENT_PROVIDERS['cybersource_rest'].update({
    'merchant_id': 'your_merchant_id',
    'key_id': 'your_key_id',
    'shared_secret': 'your_shared_secret',
})
```

Get these from the CyberSource Business Center sandbox (https://ebctest.cybersource.com).

### CyberSource Legacy (Secure Acceptance)

```python
PAYMENT_PROVIDERS['cybersource_legacy'].update({
    'access_key': 'your_access_key',
    'profile_id': 'your_profile_id',
    'secret_key': 'your_secret_key',
})
```

Get these from your Secure Acceptance profile in CyberSource Business Center.

### Stripe

```python
PAYMENT_PROVIDERS['stripe'].update({
    'secret_key': 'sk_test_xxx',
    'publishable_key': 'pk_test_xxx',
    # webhook_secret is set automatically by the test fixture
})
```

Get these from the Stripe Dashboard (https://dashboard.stripe.com/test/apikeys).

## Provider-Specific Setup

### Tunnel Commands

The project provides `inv tunnel-*` commands that manage webhook tunnels for live sandbox testing. These commands handle starting the necessary processes, extracting webhook secrets, and updating settings automatically.

| Command | Purpose |
|---------|---------|
| `inv tunnel-stripe` | Forward Stripe webhooks to local server |
| `inv tunnel-cybersource-legacy` | Expose local server via ngrok for CyberSource callbacks |
| `inv tunnel-all` | Run both tunnels concurrently |

### Stripe Webhook Setup

Stripe tests require the Stripe CLI to forward webhook events to the local test server.

**One-time authentication:**

```bash
# Authenticate the Stripe CLI (run once per machine)
docker compose exec web stripe login
```

Follow the browser prompt to complete authentication. The session persists until you explicitly log out.

**Running the tunnel:**

```bash
# In one terminal, start the webhook tunnel
docker compose exec web inv tunnel-stripe
```

The command will:
1. Start `stripe listen` forwarding to `http://localhost:8700/callback/stripe/`
2. Extract the webhook signing secret and write it to `settings_tunnels.py`
3. Print confirmation when ready

Keep this running while running tests in another terminal.

If Stripe CLI is not authenticated, Stripe tests will be skipped with a warning message.

### CyberSource Legacy Callback Setup (ngrok required)

CyberSource Legacy (Secure Acceptance) sends subscription status updates via server-to-server callbacks. Tests require ngrok to expose the local server so CyberSource can reach it.

**Running the tunnel:**

```bash
# In one terminal, start ngrok
docker compose exec web inv tunnel-cybersource-legacy
```

The command will:
1. Start ngrok forwarding to port 8702
2. Print the public URL and callback URL when established
3. Write the URL to `settings_tunnels.py`

**Configure CyberSource Business Center:**

After the tunnel starts, configure the callback URL shown in the output:
- Log into the sandbox portal (https://ebctest.cybersource.com)
- Go to your Secure Acceptance profile → Notification of Changes
- Set the callback URL to: `https://YOUR-SUBDOMAIN.ngrok.io/callback/cybersource_legacy/`

Keep the tunnel running while running tests in another terminal.

**Note**: If ngrok is not running or the callback URL is misconfigured, tests will fail with "Expected Current status" assertions.

### Running Both Tunnels

For full test coverage across all providers:

```bash
# Start both tunnels in one terminal
docker compose exec web inv tunnel-all
```

This starts both Stripe and ngrok tunnels concurrently, merging their output. Press Ctrl+C to stop both.

### CyberSource REST Cancellation Timing

CyberSource's REST API may reject immediate cancellation of newly-created subscriptions with a "subscription cannot be cancelled at this time" error. The test handles this gracefully by logging the limitation.

## Trace Report Contents

Each test generates an HTML trace report showing:

- **Sequence Diagram**: Visual timeline of all HTTP requests/responses between Browser, Server, and Payment Provider
- **Request/Response Details**: Full payloads (with sensitive data masked)
- **Screenshots**: Browser state at key points in the flow
- **Database Changes**: Records created/modified during the test
- **Sections**: Named phases (Subscribe, Change, Update, Cancel) for lifecycle tests

### Reading the Traces

1. **Lanes**: Each column represents an actor (Browser, Server, CyberSource, Stripe)
2. **Arrows**: Show the direction of requests/responses
3. **Click to expand**: Click on any entry to see full details
4. **Screenshots**: Embedded at key interaction points

## Troubleshooting

### "Provider X not configured or unavailable"

Check that credentials are set in `settings.py` for that provider.

### "Stripe CLI not authenticated"

Run `docker compose exec web stripe login` and complete the browser authentication.

### Timeouts during checkout

Payment provider sandboxes can be slow. The tests have generous timeouts, but occasional failures may occur due to network conditions.

### "Subscription cannot be cancelled at this time" (CyberSource)

This is a known CyberSource API limitation for newly-created subscriptions. The test handles this gracefully.

### Screenshots show error pages

Check the trace report for the full error response. Common issues:
- Invalid/expired sandbox credentials
- Sandbox account limits exceeded
- Test card number not valid for the sandbox

## Test Card Numbers

### CyberSource (REST and Legacy)

| Card | Number | CVV |
|------|--------|-----|
| Visa | 4111111111111111 | Any 3 digits |
| Mastercard | 5555555555554444 | Any 3 digits |

### Stripe

| Card | Number | CVV |
|------|--------|-----|
| Visa (success) | 4242424242424242 | Any 3 digits |
| Visa (decline) | 4000000000000002 | Any 3 digits |

Use any future expiration date and any billing address.
