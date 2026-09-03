"""Post-upgrade migration shipped with module version 19.0.1.0.0.

Fixes the eSewa logo missing on the website checkout for databases where the
module is ALREADY installed.

Why this is needed:
- The website checkout template `payment.form_logo` renders the stored related
  field `payment.method.image_payment_form` (resized to 45x30), not `image`.
- `image_payment_form` is a stored related field of `image`: it is computed and
  persisted when `image` is written, but a stale/empty value in the database is
  not recomputed by reading or by upgrading.
- The `payment.method` record is loaded with ``noupdate="1"``, so adding or
  changing the `image` field in `data/payment_method_data.xml` has NO effect on
  already-installed databases (the XML record is skipped on upgrade).
- `post_init_hook` only runs on a fresh install, never on `-u` (see
  ``odoo/modules/loading.py``), so it cannot fix an existing database either.

This script runs on ``-u esewa_payment``: it makes sure the eSewa payment
method has an image and forces the ORM to recompute and persist
`image_payment_form`.
"""
import base64

from odoo import SUPERUSER_ID, api
from odoo.tools import misc


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    payment_method = env.ref(
        'esewa_payment.payment_method_esewa', raise_if_not_found=False
    )
    if not payment_method:
        return
    if not payment_method.image:
        # The record has no image at all (e.g. it was created while the image
        # field was missing from the data XML): load it from the module file.
        with misc.file_open('esewa_payment/static/img/esewa-logo.png', 'rb') as image_file:
            payment_method.image = base64.b64encode(image_file.read())
    else:
        # The image is set but `image_payment_form` may be stale/empty in the
        # database. Rewriting `image` (even with the same value) invalidates the
        # stored related field and forces the ORM to recompute and persist it.
        payment_method.write({'image': payment_method.image})