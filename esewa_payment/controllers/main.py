import base64
import binascii
import json
import logging
import urllib.parse

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class EsewaController(http.Controller):

    @http.route('/payment/esewa/success', type='http', auth='public')
    def esewa_success(self, **kwargs):
        """Handle the redirect from eSewa after a completed payment."""
        data = kwargs.get('data')
        if not data:
            return request.redirect('/shop/checkout?error=No%20response%20from%20eSewa')

        transaction = self._process_esewa_response(data)
        if transaction and transaction.state == 'done':
            return request.redirect('/payment/status')
        return request.redirect('/shop/checkout?error=Payment%20verification%20failed')

    @http.route('/payment/esewa/failure', type='http', auth='public')
    def esewa_failure(self, **kwargs):
        """Handle the redirect from eSewa after a failed or canceled payment.

        Note: the transaction is canceled without verifying a signature,
        because eSewa does not sign the cancel payload and the transaction is
        matched on its (unguessable) `transaction_uuid`. This can only flip the
        state to 'cancel', never to 'done', so a forged request cannot confirm
        a payment — it can only cancel an unrelated transaction whose UUID an
        attacker happened to obtain.
        """
        data = kwargs.get('data')
        if data:
            payment_data = self._decode_esewa_data(data)
            if payment_data:
                transaction = self._find_esewa_transaction(payment_data)
                if transaction:
                    transaction.sudo()._set_canceled("Payment canceled or failed at eSewa.")
                else:
                    _logger.warning(
                        "eSewa failure callback for unknown transaction_uuid %s",
                        payment_data.get('transaction_uuid'),
                    )
        return request.redirect('/shop/checkout?error=Payment%20failed')

    @http.route('/payment/esewa/notify', type='jsonrpc', auth='public', csrf=False)
    def esewa_notify(self, **kwargs):
        """Process asynchronous status notifications from eSewa (webhook).

        Note: eSewa's v2 API is redirect-based, so this endpoint is a defensive
        integration point for asynchronous status updates.
        """
        data = kwargs.get('data')
        if not data:
            return {'status': 'error', 'message': 'Missing data'}
        transaction = self._process_esewa_response(data)
        if transaction and transaction.state == 'done':
            return {'status': 'success'}
        return {'status': 'error', 'message': 'Payment not verified'}

    def _process_esewa_response(self, data):
        """Decode the eSewa response, find the matching transaction and update it.

        :param str data: The base64-encoded payload sent by eSewa.
        :return: The updated transaction, or None if it could not be processed.
        :rtype: payment.transaction recordset or None
        """
        payment_data = self._decode_esewa_data(data)
        if not payment_data:
            return None

        transaction = self._find_esewa_transaction(payment_data)
        if transaction:
            transaction.sudo()._handle_esewa_callback(payment_data)
        else:
            _logger.warning(
                "No payment.transaction found for eSewa transaction_uuid %s",
                payment_data.get('transaction_uuid'),
            )
        return transaction

    def _find_esewa_transaction(self, payment_data):
        """Return the transaction matching the eSewa `transaction_uuid`."""
        transaction_uuid = payment_data.get('transaction_uuid')
        if not transaction_uuid:
            return None
        return request.env['payment.transaction'].sudo().search(
            [('esewa_txn_uuid', '=', transaction_uuid)], limit=1
        )

    def _decode_esewa_data(self, data):
        """Decode the base64 `data` query parameter sent by eSewa.

        Falls back to URL-decoding the payload first in case eSewa URL-encodes
        the base64 string on redirect.
        """
        try:
            return json.loads(base64.b64decode(data).decode('utf-8'))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
            pass
        try:
            decoded = base64.b64decode(urllib.parse.unquote(data)).decode('utf-8')
            return json.loads(decoded)
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
            _logger.warning("Unable to decode eSewa response payload", exc_info=True)
            return None
