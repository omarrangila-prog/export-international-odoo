from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EiCashCategory(models.Model):
    _name = 'ei.cash.category'
    _description = 'Cash expense / receipt category (backed by an approved legacy mapping)'
    _order = 'name'

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    account_id = fields.Many2one('account.account', required=True)
    legacy_code_id = fields.Many2one('ei.legacy.code', string='Legacy code',
                                     domain="[('verification_status', '=', 'approved'), ('approved_target_type', '=', 'gl_account')]")
    kind = fields.Selection([('expense', 'Expense'), ('receipt', 'Receipt'), ('other', 'Other')], default='expense', required=True)
    active = fields.Boolean(default=True)

    @api.constrains('legacy_code_id')
    def _check_legacy(self):
        for r in self.filtered('legacy_code_id'):
            c = r.legacy_code_id
            if c.verification_status != 'approved' or c.approved_target_type != 'gl_account':
                raise UserError(_("Legacy code %s is not an approved GL-account mapping.", c.legacy_code))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._link_legacy()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if 'account_id' in vals or 'legacy_code_id' in vals:
            self._link_legacy()
        return res

    def _link_legacy(self):
        for r in self.filtered('legacy_code_id'):
            r.legacy_code_id.sudo().with_context(ei_system_write=True).write({
                'linked_model': 'account.account', 'linked_res_id': r.account_id.id})
