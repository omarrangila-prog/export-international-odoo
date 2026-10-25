from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ei_show_dispatch_details = fields.Boolean('Show gate pass / truck on invoice lines', default=True,
                                              help="Customer-specific invoice wording. Layout changes beyond this need approval.")


class EiLifting(models.Model):
    _inherit = 'ei.lifting'

    invoice_move_id = fields.Many2one('account.move', readonly=True, copy=False, index=True)
    invoice_status = fields.Selection([
        ('not_billable', 'Not billable yet'), ('to_invoice', 'To invoice'), ('invoiced', 'Invoiced'),
    ], compute='_compute_invoice_status', store=True, index=True)
    billing_warning = fields.Char(compute='_compute_invoice_status', store=True)

    @api.depends('state', 'invoice_move_id', 'invoice_move_id.state')
    def _compute_invoice_status(self):
        for r in self:
            billed = bool(r.invoice_move_id) and r.invoice_move_id.state != 'cancel'
            if billed:
                r.invoice_status = 'invoiced'
            elif r.state == 'verified':
                r.invoice_status = 'to_invoice'
            else:
                r.invoice_status = 'not_billable'
            r.billing_warning = _("Lifting reversed after invoicing: issue a credit note.") if billed and r.state == 'reversed' else False

    def write(self, vals):
        if 'invoice_move_id' in vals and not self.env.context.get('ei_system'):
            from odoo.exceptions import UserError
            raise UserError(_("The invoice link is set by the invoicing wizard only."))
        return super().write(vals)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _ei_check_unpost_allowed(self):
        if any(m.state == 'posted' for m in self) and not (
                self.env.su or self.env.user.has_group('account.group_account_user')):
            raise AccessError(_("Only an accountant can un-post or cancel a posted accounting document. "
                                "Raise a credit note or ask finance."))

    def button_draft(self):
        self._ei_check_unpost_allowed()
        return super().button_draft()

    def button_cancel(self):
        self._ei_check_unpost_allowed()
        return super().button_cancel()
