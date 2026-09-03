# eSewa Payment

Accept payments with the **eSewa** payment gateway (Nepal) through Odoo's
standard payment framework, using the ePay v2 API.

## Features

- Adds the **eSewa** provider under *Accounting › Configuration › Payment
  Providers*.
- Redirect payment flow: the customer is sent to eSewa's secure checkout page
  and back to the shop afterwards.
- **HMAC-SHA256 signed** payment forms and callback verification (constant-time
  comparison).
- **Server-side confirmation** through eSewa's transaction status API, as
  required by eSewa to filter fraudulent transactions.
- Test / production environments driven by the provider's *State* toggle
  (Test Mode) — no manual URL switching.
- Demo data ships with eSewa's public sandbox credentials (`EPAYTEST`) so the
  flow can be exercised out of the box.

## Configuration

1. Install the module (it depends on `payment`; the website checkout also
   requires `website_sale`).
2. Go to *Accounting › Configuration › Payment Providers* and open the
   **eSewa** provider.
3. Fill in your **Merchant ID** (`product_code`) and **Secret Key** — eSewa
   provides these when you register as a merchant.
4. Set the provider *State* to **Test Mode** to use the sandbox environment,
   or **Enabled** to go live.
5. Publish the provider so it appears on the website checkout.

> Test credentials (public sandbox values from eSewa's documentation):
> Merchant ID `EPAYTEST`, Secret Key `8gBm/:&EnhH.1/q`.
> Sandbox test accounts log in with eSewa ID `9711111111`–`9711111114`,
> password `Nepal@123`, OTP `123456`.

## Payment flow

1. The customer picks eSewa at checkout.
2. Odoo renders a signed redirect form (ePay v2) and the customer pays on
   eSewa's page.
3. eSewa redirects back to `/payment/esewa/success` with a base64-encoded,
   signed response.
4. Odoo verifies the response signature, confirms the transaction with eSewa's
   status API, and marks the transaction **done** (or **cancel** / **error**).

## Status API behaviour

- The transaction is only marked *done* when eSewa's status endpoint answers
  with `status: COMPLETE`.
- If the status endpoint is unreachable (network error or timeout), the
  callback is still accepted because its signature was already verified with
  the shared secret; the failure is logged prominently. This *fail-open*
  policy avoids rejecting authentic payments when eSewa's infrastructure is
  briefly unavailable.

## Known limitations

- eSewa only supports the Nepalese Rupee (NPR); no currency conversion or
  enforcement is performed.
- No refunds or tokenization (eSewa ePay v2 does not offer them).
- The `/payment/esewa/notify` webhook endpoint is defensive only; eSewa's v2
  API is redirect-based.
- The failure redirect marks the transaction *canceled* without a signature
  check (eSewa does not sign cancel payloads). A forged request can only
  cancel a transaction whose `transaction_uuid` an attacker obtained — it can
  never confirm a payment.

## Tests

Standalone unit tests (no Odoo instance needed):

```bash
python3 -m unittest tests_standalone.test_esewa_logic -v
```

Odoo integration tests:

```bash
odoo-bin -i esewa_payment --test-enable --stop-after-init
```

## License

LGPL-3. The eSewa logo (`static/img/esewa-logo.png`) is the property of eSewa
and is used for identification purposes only.