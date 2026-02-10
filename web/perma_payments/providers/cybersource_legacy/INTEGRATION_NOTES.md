# CyberSource Legacy (Secure Acceptance) Integration Notes

## Field Mapping

| Our Model Field | CyberSource Field | Purpose |
|-----------------|-------------------|---------|
| `transaction_uuid` | `req_transaction_uuid` | Echoed back in callback for DB lookup; used by CyberSource for duplicate detection |
| `reference_number` | `req_reference_number` | Human-readable order ID; appears in CyberSource Business Center reports |

## Flow

1. **Outgoing**: Both fields are signed and submitted in the form POST to CyberSource
2. **Payment**: User completes payment on CyberSource's hosted page
3. **Callback**: CyberSource POSTs back with `req_` prefix on both fields
4. **Processing**: `handle_webhook` validates signature, saves `Response`, updates `SubscriptionAgreement`

## Response Logging

Callbacks are logged to `Response` subclasses (SubscriptionRequestResponse, PurchaseRequestResponse, etc.)
since they are synchronous redirects tied to a specific OutgoingTransaction.

`Response.save_callback_response()` is called directly with:
- `decision`: 'ACCEPT', 'DECLINE', 'ERROR', 'CANCEL', or 'REVIEW'
- `message`: Human-readable message from CyberSource
- `raw_response`: Full POST data (encrypted for storage)
- `provider_data`: Contains `reason_code` and optionally `payment_token`

## Decision Handling

| Decision | Success | SubscriptionAgreement Status |
|----------|---------|------------------------------|
| ACCEPT | Yes | Current |
| REVIEW | Yes | Current (flag for manual review) |
| DECLINE | No | Rejected |
| ERROR | No | Rejected |
| CANCEL | No | Aborted |

## Notes

- Both fields are included in the signed field list and verified on callback
- `reference_number` format: `PERMA-XXXX-XXXX` (15 chars)
- `transaction_uuid` format: UUID v4 (36 chars)
- CyberSource error code 104 indicates duplicate `transaction_uuid` detected
