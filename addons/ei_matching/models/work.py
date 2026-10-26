"""Home's "Match bank payment" task opens the matching screen on that line (bank officers); everyone else still gets the form."""
from odoo import api, models

from .matching import MODEL, OFFICER


class EiWork(models.AbstractModel):
    _inherit = 'ei.work'

    @api.model
    def open_task(self, model, res_id):
        if model == MODEL and int(res_id) and self.env.user.has_group(OFFICER):
            self._record(model, res_id)                      # same readability check as every task button
            return {'type': 'ir.actions.client', 'tag': 'ei_matching', 'params': {'line_id': int(res_id)}}
        return super().open_task(model, res_id)
