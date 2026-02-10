# Stripe Integration Notes

## Field Mapping

| Our Model Field | Stripe Field | Purpose |
|-----------------|--------------|---------|
| `transaction_uuid` | `client_reference_id` | Native Stripe field for linking sessions to your records |
| `reference_number` | `metadata.reference_number` | Stored for reference; visible in Stripe Dashboard |

## Flow

1. **Checkout**: Create Checkout Session with `client_reference_id` and `metadata`
2. **Payment**: User completes payment on Stripe-hosted page
3. **Callback**: Stripe redirects with `session_id` in URL
4. **Webhook**: Stripe sends events to `/callback/stripe/` endpoint
5. **Processing**: `handle_webhook` validates signature, processes event, logs to `WebhookLog`

## Webhook Event Handling

Stripe uses async webhooks for all payment lifecycle events. Events are logged to `WebhookLog`
(not `Response`) since they're not tied to synchronous OutgoingTransactions.

| Event | Action | Status Update |
|-------|--------|---------------|
| `checkout.session.completed` | Store subscription_id, customer_id in provider_data | status=Current |
| `customer.subscription.created/updated` | Update provider_data | - |
| `invoice.paid` | Calculate paid_through from period.end | status=Current |
| `invoice.payment_failed` | - | status=Hold |
| `customer.subscription.deleted` | - | status=Canceled |

## Agreement Lookup Strategy

Webhook handlers try multiple methods to find the related SubscriptionAgreement:

1. `metadata.transaction_uuid` → `SubscriptionRequest.transaction_uuid`
2. `metadata.customer_pk` + `metadata.customer_type` → `SubscriptionAgreement.customer_standing_subscription()`
3. `provider_data__subscription_id` JSONField lookup
4. `provider_data__customer_id` JSONField lookup

## Notes

- `client_reference_id` is Stripe's recommended way to link sessions to your records
- Unlike CyberSource, Stripe doesn't use our IDs for idempotency - use `idempotency_key` param if needed
- `reference_number` is purely informational in Stripe (no special handling)
- Stripe manages its own session IDs (`session_id`, `subscription_id`, `customer_id`)
- All webhook events are logged to `WebhookLog` with encrypted raw payload
- Duplicate events (same `event_id`) are automatically ignored
