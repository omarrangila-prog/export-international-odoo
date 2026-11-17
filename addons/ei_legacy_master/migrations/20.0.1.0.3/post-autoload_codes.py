from odoo import SUPERUSER_ID, api

from odoo.addons.ei_legacy_master.hooks import autoload_client_codes


def migrate(cr, version):
    """An existing database gets the client's code list on this upgrade when the deploy package carries it."""
    autoload_client_codes(api.Environment(cr, SUPERUSER_ID, {}))
