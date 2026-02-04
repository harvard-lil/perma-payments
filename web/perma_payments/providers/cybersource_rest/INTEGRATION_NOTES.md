# CyberSource REST (Flex Microform) Integration Notes

## Field Mapping

| Our Model Field | CyberSource Field | Purpose |
|-----------------|-------------------|---------|
| `transaction_uuid` | Passed to frontend, POSTed back in callback | DB lookup to find original request |
| `reference_number` | `clientReferenceInformation.code` | Merchant reference for API calls; appears in CyberSource Business Center |

## Flow

1. **Checkout**: `transaction_uuid` and `reference_number` passed to frontend via `client_config`
2. **Card Capture**: Frontend captures card via Flex Microform (client-side)
3. **Callback**: Frontend POSTs `transient_token`, `transaction_uuid`, and `request_type`
4. **API Calls**: `reference_number` used as `clientReferenceInformation.code` for:
   - `create_customer_token()` - creates TMS token
   - `create_subscription()` - creates recurring billing
5. **Processing**: `handle_webhook` saves `Response`, updates `SubscriptionAgreement`

## Response Logging

Callbacks are logged to `Response` subclasses (SubscriptionRequestResponse, etc.)
since they are synchronous callbacks tied to a specific OutgoingTransaction.

`Response.save_callback_response()` is called directly with:
- `decision`: 'ACCEPT' on success
- `message`: Success message
- `raw_response`: API results (encrypted for storage)
- `provider_data`: Contains `customer_id`, `payment_instrument_id`, `subscription_id`, `reference_number`

## Provider Data Fields

| Field | Source |
|-------|--------|
| `customer_id` | TMS customer token ID |
| `payment_instrument_id` | TMS payment instrument ID |
| `subscription_id` | Subscription ID (if subscribe request) |
| `reference_number` | Our reference number |

## Notes

- Unlike Legacy, CyberSource doesn't echo back our fields - we manage the round-trip ourselves
- `clientReferenceInformation.code` has length limits per processor (8-50 chars)
- Our `reference_number` (15 chars) fits most processors but not all (e.g., FDC Nashville Global = 8)
- `transaction_uuid` is used for DB lookup to find the original OutgoingTransaction
