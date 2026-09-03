# eSewa Payment — Agent Context

This file gives another agent (or human) everything needed to work on this
repository without prior knowledge. It is kept free of machine-specific paths,
credentials, and personal environment details. Module name: **`esewa_payment`**.

---

## 1. What this module is

An Odoo **19.x** payment provider for the **eSewa** gateway (Nepal) using the
**ePay v2 API** (redirect-based flow). It was ported from an Odoo 16-era
`payment.acquirer` module to the Odoo 19 `payment.provider` framework.

**Quick facts**

- Odoo version: 19.0 · Manifest version: `19.0.1.0.0` · License: `LGPL-3`
- `depends`: `['base', 'payment']` (`sale` is not required; `website_sale` is
  only needed for the storefront checkout redirects)
- The provider appears under *Accounting › Configuration › Payment Providers*.
- Public docs / end-user guide: `README.md` (authoritative in Odoo 19 since the
  manifest `description` is empty).

## 2. Repository layout

```
__init__.py                  post_init_hook / uninstall_hook (provider setup)
__manifest__.py              module metadata
README.md                    end-user documentation (features, config, flow)
Context.md                   this file
controllers/main.py          /payment/esewa/* HTTP routes (success, failure, notify)
models/payment_provider.py   provider model: fields, URL selection, form signing
models/payment_transaction.py  transaction model: rendering values, callbacks, status API
data/payment_method_data.xml creates payment.method record (code "esewa")
data/payment_provider_data.xml creates payment.provider record (noupdate="1")
demo/demo.xml                sandbox credentials, enabled+published for demo installs
views/payment_esewa_templates.xml  redirect form template
views/payment_provider_views.xml   backend form extension
static/img/esewa-logo.png    logo file (eSewa trademark; identification only)
static/description/icon.png  placeholder module icon (128×128, replace before publishing)
migrations/19.0.1.0.0/post-migrate.py  post-upgrade logo recompute fix
tests/test_esewa.py          Odoo integration tests (PaymentCommon-based)
tests_standalone/test_esewa_logic.py  standalone unit tests (no Odoo needed)
```

## 3. Key implementation details

### 3.1 Provider registration

- `data/payment_provider_data.xml` creates `payment_provider_esewa`
  (`code = esewa`, `state = disabled`, `noupdate="1"`), linked to
  `base.module_esewa_payment` and to the `payment.method` from
  `data/payment_method_data.xml`. Data order matters: method file loads before
  provider file.
- `post_init_hook` (in `__init__.py`):
  1. Normalises a legacy `eSewa` (capital-S) provider code to lowercase
     `esewa` **before** calling `setup_provider(env, 'esewa')` — otherwise the
     helper misses the record and checkout fails with *"Please define a payment
     method line on your payment."*
  2. Rewrites `payment.method.image` on the eSewa method to force recomputation
     of the stored related `image_payment_form` (website checkout logo).
- `uninstall_hook` calls `reset_payment_provider(env, 'esewa')` so reinstalls
  stay clean.

### 3.2 Payment flow (happy path)

1. Checkout creates a `payment.transaction`; `_get_specific_rendering_values`
   builds the ePay v2 form: `amount`, `tax_amount`, `total_amount`,
   `transaction_uuid`, `product_code`, service/delivery charges (`0.00`),
   `success_url`, `failure_url`, `signed_field_names`, `signature`.
2. The unique `transaction_uuid` is stored on the transaction (`esewa_txn_uuid`)
   so the callback can be matched (this was a historical bug — the UUID was
   generated but never saved).
3. The form auto-submits (POST) to the eSewa endpoint. Test vs production URL is
   driven by the provider **State** toggle (Test Mode), reflected in the
   read-only `esewa_environment` field.
4. On success eSewa redirects to `/payment/esewa/success?data=…`; the payload
   is base64-decoded (with a URL-encoded base64 fallback), the transaction is
   found by `transaction_uuid`, the response signature is verified, and the
   transaction is set to **done** → user lands on `/payment/status`.
5. `refId` / `transaction_code` are captured on `esewa_ref_id` /
   `esewa_transaction_id`.

**Signatures (verified with independent HMAC vectors):**

- Request: `HMAC-SHA256(secret, "total_amount=X,transaction_uuid=Y,product_code=Z")`,
  base64-encoded.
- Response: same message rebuilt from the decoded payload's
  `signed_field_names` (canonical order), compared with `hmac.compare_digest`.
- Amounts are formatted to two decimals — the exact string sent is the exact
  string signed.

### 3.3 Callback / failure handling

- Success: signature verified → **done**.
- Cancel: eSewa redirects to `/payment/esewa/failure` (no signature; eSewa does
  not sign cancels) or a callback with `status = CANCELED` → **cancel**.
- Signature mismatch / forged payload → **error**, user redirected to checkout.
- Malformed / undecodable response → graceful error redirect, no crash.

### 3.4 Status API (server-side confirmation)

`_verify_with_esewa_api()` performs a real status check:

- GET `https://rc-epay.esewa.com.np/api/epay/transaction/status/` (test) or
  `https://epay.esewa.com.np/api/epay/transaction/status/` (production) with
  `product_code`, `total_amount`, `transaction_uuid` query params (no request
  signature required per eSewa's docs).
- Transaction is marked **done** only when the response `status` is `COMPLETE`;
  other definite statuses (`PENDING`, `CANCELED`, `NOT_FOUND`, `AMBIGUOUS`,
  refunds) → **error**.
- **Fail-open policy:** network error / 10s timeout / malformed response → the
  signature-verified callback is still accepted, with a prominent warning log
  (an authentic payment is never rejected because eSewa's endpoint is briefly
  down; the HMAC already authenticates the callback).
- Missing secret or merchant id → verification fails.

### 3.5 Website checkout logo (historical fix, keep in mind)

Odoo 19's `payment.form_logo` template renders `image_payment_form` (45×30),
a **stored related field** of `payment.method.image` (64×64) — never `image`
directly. Because the method record is `noupdate="1"`, the stored related field
is **not recomputed on module upgrade**, so existing databases show the generic
placeholder on checkout. Fixed by:

- `post_init_hook` (fresh installs only — Odoo never calls it on `-u`), and
- `migrations/19.0.1.0.0/post-migrate.py` (existing databases on `-u`): ensures
  the method has an image (reads `static/img/esewa-logo.png` if missing) and
  rewrites `image` to force the ORM to recompute/persist `image_payment_form`.

## 4. Conventions and gotchas

- `payment.provider` / `payment.method` records are `noupdate="1"`: XML edits
  never fix already-installed databases — use a migration.
- `post_init_hook` runs **only on fresh install**, never on `-u` (see
  `odoo/modules/loading.py`).
- `views/payment_provider_views.xml` inherits `payment.payment_provider_form`
  — the Odoo 19 provider form id. The Odoo 16 id
  `payment.view_payment_provider_form` no longer exists (would raise
  `ParseError`).
- Routes use `type='jsonrpc'` (not the deprecated `type='json'` alias) and
  `csrf=False` for the webhook.
- Do **not** put `image` / `journal_id` / `payment_method_id` / `support_*`
  fields on the `payment.provider` record — those are Odoo 15-era
  `payment.acquirer` fields and fail on 19.
- Provider starts `state='disabled'` on purpose: `required_if_provider='esewa'`
  demands credentials as soon as the state leaves Disabled. Demo data
  (`demo/demo.xml`) pre-fills the public sandbox credentials and publishes it.
- For a provider to appear on website checkout: `state` in
  `['enabled', 'test']`, `is_published=True` for non-internal users, linked
  active `payment.method` records, matching `company_id` (and `website_id` if
  `website_payment` is installed).

## 5. How to verify changes

Standalone unit tests (no Odoo instance needed; `odoo` is stubbed):

```bash
python3 -m unittest tests_standalone.test_esewa_logic -v
```

Odoo integration tests (requires an Odoo 19 environment with this module on the
addons path):

```bash
odoo-bin -i esewa_payment --test-enable --stop-after-init
```

The standalone suite covers signatures, environment/URL switching, rendering
values, callback state transitions, status-API behaviour (mocked
`urllib.request`), route registration, and manifest/data sanity. **30 tests
pass.** The integration suite never touches the network (urllib is patched).

## 6. Known limitations

- eSewa only supports NPR; no currency conversion/restriction is enforced.
- No refunds or tokenization (ePay v2 does not offer them).
- `/payment/esewa/notify` webhook is defensive only; v2 is redirect-based.
- Storefront redirects need `website_sale` installed; without it the module
  still works as a provider for invoices/sale orders.

## 7. Still to do before publishing

- Fill in real `author` / `website` in `__manifest__.py` (currently
  placeholders).
- Replace `static/description/icon.png` with real branding.
- Initialize a git repository and push to the chosen remote (this directory is
  not a git repo yet).
- Update this file if the environment, workflow, or architecture changes.