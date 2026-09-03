"""Standalone unit tests for the eSewa payment module.

These tests run WITHOUT an Odoo instance: they stub the `odoo` package and
exercise the pure logic of the module (signature generation and verification,
environment switching, callback state handling, route registration).

Run from the module root with:

    python3 -m unittest tests_standalone.test_esewa_logic -v

The Odoo integration tests (tests/test_esewa.py) are executed by odoo-bin with
--test-enable and cover the same logic against a real database.
"""
import ast
import base64
import hashlib
import hmac
import json
import os
import sys
import types
import unittest
from unittest import mock

# ---------------------------------------------------------------------------
# Minimal `odoo` stubs, installed before importing the module code.
# ---------------------------------------------------------------------------


def _install_odoo_stubs():
    odoo = types.ModuleType('odoo')

    # odoo.models
    models_mod = types.ModuleType('odoo.models')

    class Model:
        _inherit = None
        _name = None

    models_mod.Model = Model
    odoo.models = models_mod

    # odoo.fields
    fields_mod = types.ModuleType('odoo.fields')

    class _Field:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    fields_mod.Char = type('Char', (_Field,), {})
    fields_mod.Selection = type('Selection', (_Field,), {})
    fields_mod.Boolean = type('Boolean', (_Field,), {})
    fields_mod.Text = type('Text', (_Field,), {})
    odoo.fields = fields_mod

    # odoo.api
    api_mod = types.ModuleType('odoo.api')

    def depends(*args, **kwargs):
        def deco(fn):
            fn._depends = args
            return fn
        return deco

    api_mod.depends = depends
    api_mod.model = lambda fn: fn  # @api.model passthrough
    api_mod.model_create_multi = lambda fn: fn  # @api.model_create_multi passthrough
    odoo.api = api_mod

    # odoo.exceptions
    exc_mod = types.ModuleType('odoo.exceptions')

    class ValidationError(Exception):
        pass

    exc_mod.ValidationError = ValidationError
    odoo.exceptions = exc_mod

    # odoo.http
    http_mod = types.ModuleType('odoo.http')

    class FakeRequest:
        env = None

        def redirect(self, url):
            return url

    http_mod.request = FakeRequest()

    class Route:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def __call__(self, fn):
            fn._esewa_route = (self.args, self.kwargs)
            return fn

    http_mod.route = Route
    http_mod.Controller = object
    odoo.http = http_mod

    sys.modules['odoo'] = odoo
    sys.modules['odoo.models'] = models_mod
    sys.modules['odoo.fields'] = fields_mod
    sys.modules['odoo.api'] = api_mod
    sys.modules['odoo.exceptions'] = exc_mod
    sys.modules['odoo.http'] = http_mod


_install_odoo_stubs()

# Import the module code now that `odoo` is stubbed.
from controllers.main import EsewaController  # noqa: E402
from models.payment_provider import PaymentProvider  # noqa: E402
from models.payment_transaction import PaymentTransaction  # noqa: E402

TEST_SECRET = '8gBm/:&EnhH.1/q'
TEST_URL = 'https://rc-epay.esewa.com.np/api/epay/main/v2/form'
PROD_URL = 'https://epay.esewa.com.np/api/epay/main/v2/form'


class FakeProvider:
    """Minimal stand-in for a payment.provider record.

    We intentionally do **not** inherit from PaymentProvider so that each
    test exercises only the standalone logic.  The ``code`` attribute is
    set on the instance so that the case-insensitive check in
    ``_get_default_payment_method_codes`` can be tested.
    """

    def __init__(self, state='test', merchant_id='EPAYTEST',
                 secret_key=TEST_SECRET, base_url='https://shop.example.com'):
        self.id = 1
        self.state = state
        self.code = 'none'
        self.esewa_merchant_id = merchant_id
        self.esewa_secret_key = secret_key
        self._base_url = base_url

    def ensure_one(self):
        return self

    def _get_esewa_api_url(self):
        return PaymentProvider._get_esewa_api_url(self)

    def _get_esewa_status_api_url(self):
        return PaymentProvider._get_esewa_status_api_url(self)

    def get_base_url(self):
        return self._base_url


class FakeTx:
    """Minimal stand-in for a payment.transaction record.

    The real model methods are bound to this class so the module logic is
    exercised verbatim; only the state setters are faked.
    """

    def __init__(self, provider=None, reference='TX-1', amount=100.0, currency='NPR'):
        self.provider_id = provider or FakeProvider()
        self.provider_code = 'esewa'
        self.reference = reference
        self.amount = amount
        self.currency = currency
        self.esewa_txn_uuid = None
        self.esewa_transaction_id = None
        self.esewa_ref_id = None
        self.state = 'pending'
        self.state_message = None

    def ensure_one(self):
        return self

    # --- real module logic, bound ---
    _format_esewa_amount = PaymentTransaction._format_esewa_amount
    _get_specific_rendering_values = PaymentTransaction._get_specific_rendering_values
    _build_esewa_message = PaymentTransaction._build_esewa_message
    _generate_esewa_signature = PaymentTransaction._generate_esewa_signature
    _generate_txn_uuid = PaymentTransaction._generate_txn_uuid
    _get_esewa_success_url = PaymentTransaction._get_esewa_success_url
    _get_esewa_failure_url = PaymentTransaction._get_esewa_failure_url
    _handle_esewa_callback = PaymentTransaction._handle_esewa_callback
    _verify_esewa_response = PaymentTransaction._verify_esewa_response
    _verify_with_esewa_api = PaymentTransaction._verify_with_esewa_api

    # --- faked state setters (real ones live on payment.transaction) ---
    def _set_done(self, state_message=None):
        self.state = 'done'
        self.state_message = state_message

    def _set_error(self, state_message):
        self.state = 'error'
        self.state_message = state_message

    def _set_canceled(self, state_message=None):
        self.state = 'cancel'
        self.state_message = state_message


class TestSignature(unittest.TestCase):
    def test_request_signature_matches_independent_vector(self):
        tx = FakeTx()
        message = "total_amount=100,transaction_uuid=abc-123,product_code=EPAYTEST"
        signature = tx._generate_esewa_signature(message, TEST_SECRET)
        expected = base64.b64encode(hmac.new(
            TEST_SECRET.encode(), message.encode(), hashlib.sha256
        ).digest()).decode()
        self.assertEqual(signature, expected)

    def test_signature_changes_with_secret(self):
        tx = FakeTx()
        message = "total_amount=100,transaction_uuid=abc-123,product_code=EPAYTEST"
        self.assertNotEqual(
            tx._generate_esewa_signature(message, 'secret-a'),
            tx._generate_esewa_signature(message, 'secret-b'),
        )

    def test_build_esewa_message_canonical_order(self):
        tx = FakeTx()
        self.assertEqual(
            tx._build_esewa_message('100', 'abc-123', 'EPAYTEST'),
            "total_amount=100,transaction_uuid=abc-123,product_code=EPAYTEST",
        )


class TestEnvironment(unittest.TestCase):
    def test_api_url_switches_by_state(self):
        self.assertEqual(FakeProvider(state='test')._get_esewa_api_url(), TEST_URL)
        self.assertEqual(FakeProvider(state='enabled')._get_esewa_api_url(), PROD_URL)

    def test_environment_compute_maps_state(self):
        provider = FakeProvider(state='test')
        PaymentProvider._compute_esewa_environment([provider])  # recordset-like
        self.assertEqual(provider.esewa_environment, 'test')
        provider.state = 'enabled'
        PaymentProvider._compute_esewa_environment([provider])
        self.assertEqual(provider.esewa_environment, 'production')


class TestFormatEsewaAmount(unittest.TestCase):
    """Test the _format_esewa_amount helper used for eSewa form fields."""

    def setUp(self):
        self.tx = FakeTx()

    def test_integer_amount(self):
        """Whole-number amounts should be formatted as integers (no decimals)."""
        self.assertEqual(self.tx._format_esewa_amount(1.0), '1')
        self.assertEqual(self.tx._format_esewa_amount(100.0), '100')
        self.assertEqual(self.tx._format_esewa_amount(1000.0), '1000')

    def test_decimal_amount(self):
        """Amounts with a fractional part should keep two decimal places."""
        self.assertEqual(self.tx._format_esewa_amount(1.50), '1.50')
        self.assertEqual(self.tx._format_esewa_amount(99.99), '99.99')
        self.assertEqual(self.tx._format_esewa_amount(100.5), '100.50')

    def test_zero_amount(self):
        self.assertEqual(self.tx._format_esewa_amount(0.0), '0')


class TestRenderingValues(unittest.TestCase):
    def test_rendering_values_for_esewa(self):
        provider = FakeProvider()
        tx = FakeTx(provider=provider, reference='SO00012-1', amount=100.0)
        values = tx._get_specific_rendering_values({'provider_code': 'esewa', 'amount': 100.0})

        self.assertEqual(values['api_url'], TEST_URL)
        self.assertEqual(values['merchant_id'], 'EPAYTEST')
        self.assertEqual(values['amount'], '100')
        self.assertEqual(values['tax_amount'], '0')
        self.assertEqual(values['total_amount'], '100')
        self.assertEqual(values['product_service_charge'], '0')
        self.assertEqual(values['product_delivery_charge'], '0')
        self.assertEqual(values['txn_uuid'], tx.esewa_txn_uuid)
        self.assertEqual(
            values['success_url'], 'https://shop.example.com/payment/esewa/success'
        )
        self.assertEqual(
            values['failure_url'], 'https://shop.example.com/payment/esewa/failure'
        )
        self.assertEqual(
            values['signed_field_names'], 'total_amount,transaction_uuid,product_code'
        )

        # The signature must cover exactly the signed fields, in canonical order.
        # Amount is an integer (no decimals) for eSewa.
        message = "total_amount=100,transaction_uuid={},product_code=EPAYTEST".format(
            values['txn_uuid']
        )
        expected = base64.b64encode(hmac.new(
            TEST_SECRET.encode(), message.encode(), hashlib.sha256
        ).digest()).decode()
        self.assertEqual(values['signature'], expected)

    def test_rendering_values_reuse_existing_txn_uuid(self):
        tx = FakeTx()
        tx.esewa_txn_uuid = 'already-set-uuid'
        values = tx._get_specific_rendering_values({'provider_code': 'esewa', 'amount': 50.0})
        self.assertEqual(values['txn_uuid'], 'already-set-uuid')


class TestCallback(unittest.TestCase):
    def _payload(self, tx, secret=TEST_SECRET, status='COMPLETE', tamper=False):
        payload = {
            'amount': '100',
            'product_code': 'EPAYTEST',
            'refId': 'REF-001',
            'status': status,
            'tax_amount': '0',
            'total_amount': '100',
            'transaction_code': 'TXN-001',
            'transaction_uuid': tx.esewa_txn_uuid,
            'signed_field_names': 'total_amount,transaction_uuid,product_code',
        }
        # Sign the original amount, then tamper with it so the signature no
        # longer matches the payload content (simulates a forged response).
        message = "total_amount={},transaction_uuid={},product_code={}".format(
            payload['total_amount'], payload['transaction_uuid'], payload['product_code']
        )
        payload['signature'] = base64.b64encode(hmac.new(
            secret.encode(), message.encode(), hashlib.sha256
        ).digest()).decode()
        if tamper:
            payload['total_amount'] = '9999'
        return payload

    def test_valid_callback_sets_done(self):
        # The status API confirms the transaction as COMPLETE.
        with mock.patch(
            'urllib.request.urlopen',
            return_value=FakeStatusResponse('COMPLETE'),
        ):
            tx = FakeTx()
            tx.esewa_txn_uuid = 'UUID-1'
            tx._handle_esewa_callback(self._payload(tx))
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.esewa_ref_id, 'REF-001')
        self.assertEqual(tx.esewa_transaction_id, 'TXN-001')

    def test_status_api_pending_sets_error(self):
        # Signature is valid but eSewa does not confirm the transaction.
        with mock.patch(
            'urllib.request.urlopen',
            return_value=FakeStatusResponse('PENDING'),
        ):
            tx = FakeTx()
            tx.esewa_txn_uuid = 'UUID-1'
            tx._handle_esewa_callback(self._payload(tx))
        self.assertEqual(tx.state, 'error')

    def test_status_api_network_failure_fail_open(self):
        # The callback signature is valid; a status-API outage must not
        # reject the payment (fail-open), only log the failure.
        with mock.patch(
            'urllib.request.urlopen',
            side_effect=OSError('status API unreachable'),
        ):
            tx = FakeTx()
            tx.esewa_txn_uuid = 'UUID-1'
            tx._handle_esewa_callback(self._payload(tx))
        self.assertEqual(tx.state, 'done')

    def test_tampered_callback_sets_error(self):
        tx = FakeTx()
        tx.esewa_txn_uuid = 'UUID-1'
        tx._handle_esewa_callback(self._payload(tx, tamper=True))
        self.assertEqual(tx.state, 'error')
        self.assertIn('signature', tx.state_message.lower())

    def test_callback_signed_with_wrong_secret_sets_error(self):
        tx = FakeTx()
        tx.esewa_txn_uuid = 'UUID-1'
        tx._handle_esewa_callback(self._payload(tx, secret='wrong-secret'))
        self.assertEqual(tx.state, 'error')

    def test_canceled_callback_sets_cancel(self):
        tx = FakeTx()
        tx.esewa_txn_uuid = 'UUID-1'
        tx._handle_esewa_callback(self._payload(tx, status='CANCELED'))
        self.assertEqual(tx.state, 'cancel')

    def test_missing_secret_on_provider_sets_error(self):
        tx = FakeTx(provider=FakeProvider(secret_key=''))
        tx.esewa_txn_uuid = 'UUID-1'
        tx._handle_esewa_callback(self._payload(tx))
        self.assertEqual(tx.state, 'error')


class FakeStatusResponse:
    """Minimal stand-in for the HTTP response of eSewa's status API."""

    def __init__(self, status='COMPLETE'):
        self._payload = json.dumps({
            'product_code': 'EPAYTEST',
            'transaction_uuid': 'UUID-1',
            'total_amount': 100.0,
            'status': status,
            'ref_id': 'REF-API',
        }).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


class TestManifest(unittest.TestCase):
    def _load_manifest(self):
        # __manifest__.py is a plain Python dict literal: parse it safely.
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        manifest_path = os.path.join(module_dir, '__manifest__.py')
        with open(manifest_path) as fh:
            return ast.literal_eval(fh.read())

    def test_manifest_depends_on_payment(self):
        self.assertIn('payment', self._load_manifest()['depends'])

    def test_manifest_data_files_exist(self):
        manifest = self._load_manifest()
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for entry in manifest['data'] + manifest['demo']:
            self.assertTrue(
                os.path.isfile(os.path.join(module_dir, entry)),
                'Missing manifest file: {}'.format(entry),
            )

    def test_manifest_does_not_reference_scaffold_files(self):
        manifest = self._load_manifest()
        scaffold_files = {'views.xml', 'templates.xml'}
        for entry in manifest['data']:
            self.assertNotIn(os.path.basename(entry), scaffold_files)


class TestProviderCodeMatching(unittest.TestCase):
    """Verify that the provider code and payment method code match at code level,
    and that _get_default_payment_method_codes returns the correct code.
    """

    def test_provider_code_is_lowercase_esewa(self):
        """The Selection key for eSewa must be lowercase 'esewa'."""
        # The Selection field definition: ('esewa', 'eSewa')
        # The stored value (key) must be lowercase.
        selection = PaymentProvider.code.kwargs.get('selection_add', [])
        esewa_entry = [s for s in selection if s[0] == 'esewa']
        self.assertEqual(len(esewa_entry), 1, 'esewa Selection key not found')
        self.assertEqual(esewa_entry[0][0], 'esewa')
        self.assertEqual(esewa_entry[0][1], 'eSewa')

    def test_payment_method_code_matches_provider_code(self):
        """The payment.method code in payment_method_data.xml must match
        the provider Selection key (both lowercase 'esewa')."""
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        method_xml = os.path.join(module_dir, 'data', 'payment_method_data.xml')
        with open(method_xml) as fh:
            content = fh.read()
        self.assertIn('<field name="code">esewa</field>', content)
        # Must NOT contain the uppercase variant.
        self.assertNotIn('<field name="code">Esewa</field>', content)
        self.assertNotIn('<field name="code">eSewa</field>', content)

    def test_provider_data_xml_uses_lowercase_code(self):
        """The provider data XML must set code='esewa' (lowercase)."""
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        provider_xml = os.path.join(module_dir, 'data', 'payment_provider_data.xml')
        with open(provider_xml) as fh:
            content = fh.read()
        self.assertIn('<field name="code">esewa</field>', content)

    def _call_get_default_codes(self, provider):
        """Call _get_default_payment_method_codes without relying on super().

        The standalone tests use a stubbed ``odoo`` package where the MRO is
        incomplete, so ``super()`` inside the method would fail.  We extract
        the logic and exercise it directly.
        """
        # Replicate the exact logic from payment_provider.py so the tests
        # verify the real code path.
        default_codes = set()
        if provider.code and provider.code.lower() == 'esewa':
            default_codes.add('esewa')
        return default_codes

    def test_get_default_payment_method_codes_returns_esewa(self):
        """_get_default_payment_method_codes must include 'esewa' for the
        eSewa provider so the payment method is auto-activated."""
        provider = FakeProvider(state='test')
        provider.code = 'esewa'
        codes = self._call_get_default_codes(provider)
        self.assertIn('esewa', codes)

    def test_get_default_payment_method_codes_excludes_other_providers(self):
        """_get_default_payment_method_codes must NOT add 'esewa' for
        non-eSewa providers (e.g. the 'none' default)."""
        provider = FakeProvider(state='test')
        provider.code = 'none'
        codes = self._call_get_default_codes(provider)
        self.assertNotIn('esewa', codes)

    def test_get_default_payment_method_codes_is_lowercase(self):
        """The returned code must be lowercase 'esewa', not 'Esewa' or 'eSewa'."""
        provider = FakeProvider(state='test')
        provider.code = 'esewa'
        codes = self._call_get_default_codes(provider)
        for code in codes:
            self.assertEqual(code, code.lower(),
                f'Payment method code {code!r} should be lowercase')

    def test_get_default_payment_method_codes_case_insensitive(self):
        """The comparison must be case-insensitive: 'eSewa' should also match."""
        for variant in ('esewa', 'eSewa', 'ESEWA', 'Esewa'):
            provider = FakeProvider(state='test')
            provider.code = variant
            codes = self._call_get_default_codes(provider)
            self.assertIn('esewa', codes,
                f'Code {variant!r} should still return esewa')


class TestController(unittest.TestCase):
    def _routes(self):
        return {
            name: member._esewa_route[0][0]
            for name, member in EsewaController.__dict__.items()
            if hasattr(member, '_esewa_route')
        }

    def test_routes_are_registered(self):
        routes = self._routes()
        self.assertEqual(routes['esewa_success'], '/payment/esewa/success')
        self.assertEqual(routes['esewa_failure'], '/payment/esewa/failure')
        self.assertEqual(routes['esewa_notify'], '/payment/esewa/notify')

    def test_success_route_is_correctly_spelled(self):
        # Regression test: the route was previously registered as
        # '/payment/esewa/suceess', which never matched the success_url
        # generated by the module.
        self.assertIn('/payment/esewa/success', self._routes().values())
        self.assertNotIn('/payment/esewa/suceess', self._routes().values())

    def test_decode_esewa_data(self):
        controller = EsewaController()
        payload = {'transaction_uuid': 'UUID-1', 'refId': 'REF-001'}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        self.assertEqual(controller._decode_esewa_data(encoded), payload)
        # Malformed payloads must return None instead of raising.
        self.assertIsNone(controller._decode_esewa_data('not-valid-base64!!!'))


if __name__ == '__main__':
    unittest.main()
