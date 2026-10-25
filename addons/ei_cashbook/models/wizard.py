from odoo import fields, models


class EiCashDecisionWizard(models.TransientModel):
    _name = 'ei.cash.decision.wizard'
    _description = 'Reject or reverse a cash voucher'

    decision = fields.Selection([('reject', 'Reject'), ('reverse', 'Reverse')], required=True)
    reason = fields.Char(required=True)

    def action_apply(self):
        vouchers = self.env['ei.cash.voucher'].browse(self.env.context.get('active_ids', []))
        if self.decision == 'reject':
            vouchers.action_reject(self.reason)
        else:
            vouchers.action_reverse(self.reason)
        return {'type': 'ir.actions.act_window_close'}
