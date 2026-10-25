from odoo import fields, models, _
from odoo.exceptions import UserError

ALLOWED = {('ei.da', 'action_cancel'), ('ei.contract', 'action_cancel'), ('ei.da.line', 'action_authorise_over_quantity')}


class EiReasonWizard(models.TransientModel):
    _name = 'ei.reason.wizard'
    _description = 'Ask for a reason, then run a controlled action'

    res_model = fields.Char(required=True)
    method = fields.Char(required=True)
    reason = fields.Char(required=True)

    def action_apply(self):
        if (self.res_model, self.method) not in ALLOWED:
            raise UserError(_("Action not allowed."))
        recs = self.env[self.res_model].browse(self.env.context.get('active_ids', []))
        getattr(recs, self.method)(self.reason)
        return {'type': 'ir.actions.act_window_close'}
