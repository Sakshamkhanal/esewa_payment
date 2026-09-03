import base64
import hashlib
import hmac
import json
from unittest import mock

from odoo.addons.payment.tests.common import PaymentCommon
from odoo.tests import tagged

TEST_MERCHANT_ID = 'EPAYTEST'
TEST_SECRET_KEY = '8gBm/:&EnhH.1/q'


@tagged('post_install', '-at_install')
class EsewaPaymentTest(PaymentCommon):
    """Integration tests for the eSewa payment provider.

    Run with: odoo-bin -i esewa_payment --test-enable --stop-after-init
    """

    def setUp(self):
        super().setUp()

        self.esewa_provider = self._prepare_provider('esewa', update_values={
            'state': 'test',
            'esewa_merchant_id': TEST_MERCHANT_ID,
            'esewa_secret_key': TEST_SECRET_KEY,
        })
        self.esewa_provider.redirect_form_view_id = self.env.ref(
            'esewa_payment.payment_esewa_redirect_form'
        )

    # === CONFIGURATION ===

    def test_environment_switches_api_url(self):
        self.assertEqual(
            self.esewa_provider._get_esewa_api_url(),
            'https://rc-epay.esewa.com.np/api/epay/main/v2/form',
        )
        self.esewa_provider.state = 'enabled'
        self.assertEqual(
            self.esewa_provider._get_esewa_api_url(),
            'https://epay.esewa.com.np/api/epay/main/v2/form',
        )

    def test_environment_compute_from_state(self):
        self.assertEqual(self.esewa_provider.esewa_environment, 'test')
        self.esewa_provider.state = 'enabled'
        self.assertEqual(self.esewa_provider.esewa_environment, 'production')

    # === PAYMENT FLOW - RENDERING ===

    def test_rendering_values_and_signature(self):
        tx = self._create_transaction(flow='redirect', provider_id=self.esewa_provider.id)
        processing_values = {
            'provider_id': self.esewa_provider.id,
            'provider_code': 'esewa',
            'reference': tx.reference,
            'amount': self.amount,
            'currency_id': self.currency.id,
            'partner_id': self.partner.id,
        }
        values = tx._get_specific_rendering_values(processing_values)

        self.assertEqual(
            values['api_url'], 'https://rc-epay.esewa.com.np/api/epay/main/v2/form'
        )
        self.assertEqual(values['merchant_id'], TEST_MERCHANT_ID)
        self.assertEqual(values['txn_uuid'], tx.esewa_txn_uuid)
        self.assertEqual(values['total_amount'], str(int(self.amount)))
        self.assertIn('total_amount', values['signed_field_names'])

        # Independently recompute the expected signature and compare.
        message = "total_amount={},transaction_uuid={},product_code={}".format(
            values['total_amount'], values['txn_uuid'], values['merchant_id']
        )
        expected = base64.b64encode(hmac.new(
            TEST_SECRET_KEY.encode(), message.encode(), hashlib.sha256
        ).digest()).decode()
        self.assertEqual(values['signature'], expected)

    # === PAYMENT FLOW - CALLBACK ===

    def _create_callback_ready_tx(self):
        tx = self._create_transaction(flow='redirect', provider_id=self.esewa_provider.id)
        tx.esewa_txn_uuid = 'TEST-UUID-{}'.format(tx.id)
        return tx

    def _callback_payload(self, tx, status='COMPLETE', tamper=False):
        payload = {
            'amount': str(int(self.amount)),
            'product_code': TEST_MERCHANT_ID,
            'refId': 'REF-123',
            'status': status,
            'tax_amount': '0',
            'total_amount': str(int(self.amount)),
            'transaction_code': 'TXN-123',
            'transaction_uuid': tx.esewa_txn_uuid,
            'signed_field_names': 'total_amount,transaction_uuid,product_code',
        }
        # Sign the original amount, then tamper with it so the signature no
        # longer matches the payload content (simulates a forged response).
        message = "total_amount={},transaction_uuid={},product_code={}".format(
            payload['total_amount'], payload['transaction_uuid'], payload['product_code']
        )
        payload['signature'] = base64.b64encode(hmac.new(
            TEST_SECRET_KEY.encode(), message.encode(), hashlib.sha256
        ).digest()).decode()
        if tamper:
            payload['total_amount'] = '9999'
        return payload

    def _mock_status_api(self, status='COMPLETE'):
        """Mock the outbound status-API request with the given eSewa status."""
        class FakeResponse:
            def __init__(self):
                self._payload = json.dumps({'status': status}).encode('utf-8')

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return self._payload

        return mock.patch('urllib.request.urlopen', return_value=FakeResponse())

    def test_callback_valid_signature_sets_done(self):
        with self._mock_status_api('COMPLETE'):
            tx = self._create_callback_ready_tx()
            tx._handle_esewa_callback(self._callback_payload(tx))
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.esewa_ref_id, 'REF-123')
        self.assertEqual(tx.esewa_transaction_id, 'TXN-123')

    def test_callback_status_api_not_confirmed_sets_error(self):
        # The signature is valid but eSewa's status API does not confirm it.
        with self._mock_status_api('PENDING'):
            tx = self._create_callback_ready_tx()
            tx._handle_esewa_callback(self._callback_payload(tx))
        self.assertEqual(tx.state, 'error')

    def test_callback_invalid_signature_sets_error(self):
        tx = self._create_callback_ready_tx()
        tx._handle_esewa_callback(self._callback_payload(tx, tamper=True))
        self.assertEqual(tx.state, 'error')
        self.assertIn('signature', tx.state_message.lower())

    def test_callback_canceled_sets_cancel(self):
        tx = self._create_callback_ready_tx()
        tx._handle_esewa_callback(self._callback_payload(tx, status='CANCELED'))
        self.assertEqual(tx.state, 'cancel')
