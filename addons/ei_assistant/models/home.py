"""Home's question box: offered only to people who have at least one question the assistant can answer for them."""
from odoo import api, models


class EiHomeAsk(models.AbstractModel):
    _inherit = 'ei.home'

    @api.model
    def get_data(self, period=None):
        data = super().get_data(period)
        starters = self.env['ei.assistant'].starters()
        if starters:
            data['ask'] = {'example': starters[0], 'starters': starters[:3]}
        return data
