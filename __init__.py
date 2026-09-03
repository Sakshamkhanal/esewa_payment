from . import controllers
from . import models

from odoo.addons.payment import setup_provider, reset_payment_provider


def post_init_hook(env):
    # Normalise the provider code BEFORE calling setup_provider so that the
    # helper can locate the record by the lowercase key 'esewa'.  The
    # noupdate="1" flag on the provider data XML means a previously-created
    # record whose code was stored as 'eSewa' (capital S) would never be
    # corrected on upgrade; without this fix setup_provider searches for
    # 'esewa', misses the record, and no payment.method.line is created →
    # the checkout raises "Please define a payment method line on your payment."
    env["payment.provider"].sudo().search(
        [("code", "=", "eSewa")]
    ).write({"code": "esewa"})
    setup_provider(env, 'esewa')

    # Force the `image_payment_form` related field to recompute.  The website
    # checkout template (payment.form_logo) renders `image_payment_form`, not
    # `image`, and the stored related field is not recomputed by reading it.
    # Rewriting the same image value triggers the ORM to recompute and persist
    # the related field.  Scoped to the eSewa method only.
    # NOTE: this hook only runs on a fresh INSTALL (never on `-u`; see
    # odoo/modules/loading.py).  Databases where the module is already
    # installed are fixed by the post-migration script in
    # migrations/0.2/post-migrate.py, which performs the same recompute.
    pm = env.ref('esewa_payment.payment_method_esewa', raise_if_not_found=False)
    if pm and pm.image:
        pm.write({"image": pm.image})


def uninstall_hook(env):
    reset_payment_provider(env, 'esewa')
