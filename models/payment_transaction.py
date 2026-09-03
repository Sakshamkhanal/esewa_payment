import base64
import hashlib
import hmac
import json
import logging
import urllib.parse
import urllib.request
import uuid

from odoo import fields, models

_logger = logging.getLogger(__name__)

# The eSewa fields covered by the HMAC-SHA256 signature, in canonical order.
ESEWA_SIGNED_FIELDS = ('total_amount', 'transaction_uuid', 'product_code')

# Timeout (seconds) for the outbound status-API request.
ESEWA_STATUS_API_TIMEOUT = 10


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    esewa_transaction_id = fields.Char(string="eSewa Transaction ID")
    esewa_ref_id = fields.Char(string="eSewa Reference ID")
    esewa_txn_uuid = fields.Char(
        string="eSewa Transaction UUID",
        help="The unique transaction identifier sent to eSewa, used to match callbacks.",
    )

    # === PAYMENT FLOW - RENDERING ===

    def _format_esewa_amount(self, amount):
        """Format an amount for the eSewa ePay v2 API.

        eSewa's official form examples use plain integers when the amount
        has no fractional part (e.g. ``100`` instead of ``100.00``).  Using
        trailing ``.00`` can cause signature mismatches and payment failures
        on eSewa's side.

        :param float amount: The numeric amount.
        :return: The formatted amount string.
        :rtype: str
        """
        if amount == int(amount):
            return str(int(amount))
        return f'{amount:.2f}'

    def _get_specific_rendering_values(self, processing_values):
        """Return the eSewa-specific values used to render the redirect form.

        Note: `self.ensure_one()`

        :param dict processing_values: The generic processing values of the transaction.
        :return: The dict of provider-specific rendering values.
        :rtype: dict
        """
        if self.provider_code != 'esewa':
            return super()._get_specific_rendering_values(processing_values)

        provider = self.provider_id
        merchant_id = provider.esewa_merchant_id
        secret_key = provider.esewa_secret_key

        # Generate (once) a unique identifier that eSewa will echo back in its
        # response, allowing us to match the callback to this transaction.
        txn_uuid = self.esewa_txn_uuid or self._generate_txn_uuid()
        self.esewa_txn_uuid = txn_uuid

        # eSewa expects plain integers when the amount has no fractional part
        # (e.g. ``1`` not ``1.00``).  The exact string sent in the form must
        # also be the one covered by the signature.
        total_amount = self._format_esewa_amount(processing_values['amount'])
        message = self._build_esewa_message(total_amount, txn_uuid, merchant_id)
        signature = self._generate_esewa_signature(message, secret_key)

        _logger.info(
            'eSewa rendering values: amount=%s, txn_uuid=%s, message=%s',
            total_amount, txn_uuid, message,
        )

        return {
            'api_url': provider._get_esewa_api_url(),
            'merchant_id': merchant_id,
            'amount': total_amount,
            'tax_amount': '0',
            'total_amount': total_amount,
            'txn_uuid': txn_uuid,
            'product_service_charge': '0',
            'product_delivery_charge': '0',
            'success_url': self._get_esewa_success_url(),
            'failure_url': self._get_esewa_failure_url(),
            'signed_field_names': ','.join(ESEWA_SIGNED_FIELDS),
            'signature': signature,
        }

    def _build_esewa_message(self, total_amount, txn_uuid, merchant_id):
        """Build the canonical message signed with HMAC-SHA256.

        The field order and formatting must match exactly what eSewa expects:
        ``total_amount=X,transaction_uuid=Y,product_code=Z`` (no spaces).
        """
        return f'total_amount={total_amount},transaction_uuid={txn_uuid},product_code={merchant_id}'

    def _generate_esewa_signature(self, message, secret_key):
        """Generate the base64-encoded HMAC-SHA256 signature of the message."""
        digest = hmac.new(
            secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode('utf-8')

    def _generate_txn_uuid(self):
        """Generate a unique transaction identifier for eSewa."""
        return str(uuid.uuid4())

    def _get_esewa_success_url(self):
        """Return the URL eSewa redirects to after a successful payment."""
        base_url = self.provider_id.get_base_url()
        return f'{base_url}/payment/esewa/success'

    def _get_esewa_failure_url(self):
        """Return the URL eSewa redirects to after a failed or canceled payment."""
        base_url = self.provider_id.get_base_url()
        return f'{base_url}/payment/esewa/failure'

    # === PAYMENT FLOW - CALLBACK ===

    def _handle_esewa_callback(self, payment_data):
        """Process the decoded eSewa response for this transaction.

        Captures the eSewa identifiers, then verifies the response signature
        and confirms the status with eSewa before marking the transaction as
        done. Canceled payments are marked as canceled without a signature
        check (eSewa does not sign the cancel payload).

        :param dict payment_data: The decoded eSewa callback payload.
        :return: The decoded payment data, so callers can react to the outcome.
        :rtype: dict
        """
        self.ensure_one()

        self.esewa_transaction_id = payment_data.get('transaction_code')
        self.esewa_ref_id = payment_data.get('refId')

        if payment_data.get('status') == 'CANCELED':
            self._set_canceled("Payment canceled by the customer on eSewa.")
            return payment_data

        if self._verify_esewa_response(payment_data):
            self._set_done()
        else:
            self._set_error(
                "Payment not verified: the eSewa response signature is invalid "
                "or the transaction status is not confirmed."
            )
        return payment_data

    def _verify_esewa_response(self, payment_data):
        """Verify the eSewa response signature and confirm the transaction status.

        The response payload contains a `signature` field computed over the
        fields listed in `signed_field_names` with the same HMAC-SHA256 scheme
        as the payment request. The comparison is done in constant time, then
        the status is confirmed with eSewa's status API.

        :param dict payment_data: The decoded eSewa callback payload.
        :return: Whether the response is authentic and confirmed.
        :rtype: bool
        """
        secret_key = self.provider_id.esewa_secret_key
        if not secret_key:
            _logger.warning(
                "eSewa secret key is not set on provider %s", self.provider_id.id
            )
            return False

        field_names = payment_data.get('signed_field_names') or ','.join(ESEWA_SIGNED_FIELDS)
        message = ','.join(
            f'{name}={payment_data.get(name, "")}'
            for name in field_names.split(',')
        )
        expected = self._generate_esewa_signature(message, secret_key)
        received = payment_data.get('signature')

        if not received or not hmac.compare_digest(expected, received):
            _logger.warning("eSewa signature mismatch for transaction %s", self.reference)
            return False

        return self._verify_with_esewa_api(payment_data)

    def _verify_with_esewa_api(self, payment_data):
        """Confirm the transaction status with eSewa's transaction status API.

        eSewa requires merchants to confirm successful payments through the
        status check endpoint to filter out fraudulent transactions
        (see https://developer.esewa.com.np/pages/Epay - Status Check).

        The endpoint is a GET request with `product_code`, `total_amount` and
        `transaction_uuid` as query parameters; no signature is required on the
        request itself. The transaction is only confirmed when the response
        `status` is 'COMPLETE'.

        Fail-open policy: if the status API cannot be reached (network error,
        timeout or malformed response), the transaction is still accepted
        because the callback signature was already verified with the shared
        secret. Rejecting otherwise-authentic payments because eSewa's
        endpoint is briefly unavailable would be worse than accepting them;
        the failure is logged prominently so it can be monitored.

        :param dict payment_data: The decoded eSewa callback payload.
        :return: Whether eSewa confirms the transaction as COMPLETE.
        :rtype: bool
        """
        provider = self.provider_id
        if not provider.esewa_secret_key or not provider.esewa_merchant_id:
            _logger.warning(
                "eSewa status API: credentials missing on provider %s", provider.id
            )
            return False

        total_amount = payment_data.get('total_amount')
        try:
            total_amount_str = self._format_esewa_amount(float(total_amount))
        except (TypeError, ValueError):
            total_amount_str = str(total_amount)
        query = urllib.parse.urlencode({
            'product_code': provider.esewa_merchant_id,
            'total_amount': total_amount_str,
            'transaction_uuid': payment_data.get('transaction_uuid'),
        })
        url = f'{provider._get_esewa_status_api_url()}?{query}'

        try:
            with urllib.request.urlopen(url, timeout=ESEWA_STATUS_API_TIMEOUT) as response:
                response_data = json.loads(response.read().decode('utf-8'))
        except Exception:  # network errors, timeouts, malformed responses
            _logger.warning(
                "eSewa status API request failed for transaction %s; accepting "
                "the signature-verified callback (fail-open)",
                self.reference,
                exc_info=True,
            )
            return True

        if response_data.get('status') == 'COMPLETE':
            return True
        _logger.warning(
            "eSewa status API did not confirm transaction %s: %s",
            self.reference, response_data.get('status'),
        )
        return False
