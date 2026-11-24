from odoo import SUPERUSER_ID, api

from odoo.addons.export_international import open_everything


def migrate(cr, version):
    open_everything(api.Environment(cr, SUPERUSER_ID, {}))
