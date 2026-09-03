import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Payment form endpoint (ePay v2 API) per environment.
ESEWA_API_URLS = {
    'test': "https://rc-epay.esewa.com.np/api/epay/main/v2/form",
    'production': "https://epay.esewa.com.np/api/epay/main/v2/form",
}

# Transaction status endpoint (ePay v2 status check API) per environment.
ESEWA_STATUS_API_URLS = {
    'test': "https://rc-epay.esewa.com.np/api/epay/transaction/status/",
    'production': "https://epay.esewa.com.np/api/epay/transaction/status/",
}


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('esewa', 'eSewa')],
        ondelete={'esewa': 'set default'},
    )

    # ------------------------------------------------------------------
    # Normalise the provider code to lowercase so that it always matches
    # the payment.method code ('esewa').  The Selection key is defined as
    # lowercase, but a record created through the ORM or XML with a
    # wrong-case value (e.g. 'eSewa') would silently break payment-method
    # line creation because _get_default_payment_method_codes uses an
    # exact string comparison.
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code') and vals['code'].lower() == 'esewa':
                vals['code'] = 'esewa'
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('code') and vals['code'].lower() == 'esewa':
            vals['code'] = 'esewa'
        return super().write(vals)

    esewa_merchant_id = fields.Char(
        string="Merchant ID",
        required_if_provider='esewa',
        help="Your eSewa merchant/product code. Use EPAYTEST for testing.",
        groups='base.group_system',
    )

    esewa_secret_key = fields.Char(
        string="Secret Key",
        required_if_provider='esewa',
        help="Your eSewa secret key, used to generate and verify HMAC-SHA256 signatures.",
        groups='base.group_system',
    )

    # Reflects the provider environment: 'test' when the provider State is set
    # to "Test Mode", 'production' otherwise. The State field of the base
    # provider form acts as the Test/Production toggle.
    esewa_environment = fields.Selection(
        selection=[('test', 'Test Environment'), ('production', 'Production Environment')],
        string="Environment",
        compute='_compute_esewa_environment',
        store=True,
    )

    @api.depends('state')
    def _compute_esewa_environment(self):
        for provider in self:
            provider.esewa_environment = 'test' if provider.state == 'test' else 'production'

    def _get_default_payment_method_codes(self):
        """Return the default payment methods for this provider.

        Override of `payment` to return the ``esewa`` code so that the matching
        `payment.method` record is automatically activated when the provider is
        switched to Test Mode or Enabled.

        The comparison is intentionally case-insensitive so that a legacy
        provider record whose code was stored as ``eSewa`` (capital S) still
        gets the correct payment method line created.

        Note: `self.ensure_one()`
        :return: The default payment method codes.
        :rtype: set
        """
        default_codes = super()._get_default_payment_method_codes()
        if self.code and self.code.lower() == 'esewa':
            default_codes.add('esewa')
        return default_codes

    def _get_esewa_api_url(self):
        """Return the eSewa payment form endpoint matching the provider environment."""
        self.ensure_one()
        return ESEWA_API_URLS['test' if self.state == 'test' else 'production']

    def _get_esewa_status_api_url(self):
        """Return the eSewa transaction status endpoint matching the provider environment."""
        self.ensure_one()
        return ESEWA_STATUS_API_URLS['test' if self.state == 'test' else 'production']
