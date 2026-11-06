from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """PINs stored before the key fingerprint existed were stored under the key in use now: record that, so a later key change is noticed."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Cred = env['ei.pin.credential']
    Cred.search([('key_id', '=', False)]).write({'key_id': Cred._key_id()})
