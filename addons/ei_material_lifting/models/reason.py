from odoo import models


class EiReasonWizardLifting(models.TransientModel):
    _inherit = 'ei.reason.wizard'

    def _allowed(self):
        return super()._allowed() | {('ei.lifting', 'action_reverse')}
