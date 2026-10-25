from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .bank_parsing import normalise_text


class EiPartnerAlias(models.Model):
    _name = 'ei.partner.alias'
    _description = 'Approved alias of a party for bank narration matching'
    _order = 'alias'

    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    partner_id = fields.Many2one('res.partner', required=True, index=True, ondelete='cascade')
    alias = fields.Char(required=True, help="Text that appears in bank narrations for this party.")
    alias_norm = fields.Char(compute='_compute_alias_norm', store=True, index=True)
    legacy_code_id = fields.Many2one('ei.legacy.code', string='Legacy code', ondelete='set null')
    state = fields.Selection([('proposed', 'Proposed'), ('approved', 'Approved')], default='proposed', required=True)
    approved_by = fields.Many2one('res.users', readonly=True)

    _uniq = models.Constraint('unique(company_id, alias_norm, partner_id)', 'This alias already exists for the party.')

    @api.depends('alias')
    def _compute_alias_norm(self):
        for r in self:
            r.alias_norm = normalise_text(r.alias)

    @api.constrains('alias')
    def _check_alias_len(self):
        for r in self:
            if len(r.alias_norm or '') < 4:
                raise UserError(_("Alias %r is too short (minimum 4 characters) to match narrations safely.", r.alias))

    def action_approve(self):
        if not self.env.user.has_group('ei_bank_operations.group_ei_bank_approver'):
            raise AccessError(_("Only a bank approver can approve aliases."))
        self.write({'state': 'approved', 'approved_by': self.env.user.id})
