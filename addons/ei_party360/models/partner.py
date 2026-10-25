from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_open_party360(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'ei_party360', 'name': self.name,
                'params': {'partner_id': self.id}, 'target': 'current'}
