from odoo import models


class EiReasonWizardOrders(models.TransientModel):
    _inherit = 'ei.reason.wizard'

    def _allowed(self):
        return super()._allowed() | {('ei.daily.order', 'action_cancel')}
