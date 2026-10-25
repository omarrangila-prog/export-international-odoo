import re

from odoo import models, _
from odoo.exceptions import AccessError, UserError

from .bank_parsing import normalise_text


class EiLegacyCode(models.Model):
    _inherit = 'ei.legacy.code'

    def _digits(self):
        return re.sub(r'\D', '', self.legacy_code)

    def action_materialise(self, partner=None):
        """Create (or link) the Odoo record for an APPROVED mapping. Idempotent; never guesses a type."""
        if not self.env.user.has_group('ei_legacy_master.group_ei_mapping_approver'):
            raise AccessError(_("Only a mapping approver can create Odoo records from mappings."))
        Alias = self.env['ei.partner.alias']
        for r in self:
            if r.verification_status != 'approved':
                raise UserError(_("%s is not approved.", r.legacy_code))
            if r.linked_res_id:
                continue
            t = r.approved_target_type
            if t in ('bank_journal', 'cash_journal'):
                rec = self.env['account.journal'].sudo().with_company(r.company_id).create({
                    'name': r.original_name, 'type': 'bank' if t == 'bank_journal' else 'cash',
                    'code': ('B' if t == 'bank_journal' else 'C') + r._digits(), 'company_id': r.company_id.id})
            elif t == 'res_partner':
                if partner:
                    rec = partner
                else:
                    rec = self.env['res.partner'].sudo().create({
                        'name': r.original_name, 'ref': r.legacy_code, 'company_id': r.company_id.id,
                        'is_company': True})
                for text in {r.nickname, r.original_name}:
                    norm = normalise_text(text)
                    if len(norm) >= 4 and not Alias.sudo().search_count([
                            ('company_id', '=', r.company_id.id), ('partner_id', '=', rec.id), ('alias_norm', '=', norm)]):
                        Alias.sudo().create({'company_id': r.company_id.id, 'partner_id': rec.id, 'alias': text,
                                             'legacy_code_id': r.id})
            else:
                raise UserError(_("%(c)s is approved as '%(t)s'; the Odoo record for that type is created by the "
                                  "accountant (or its own module), not automatically.", c=r.legacy_code, t=t))
            r.with_context(ei_system_write=True).write({'linked_model': rec._name, 'linked_res_id': rec.id})
