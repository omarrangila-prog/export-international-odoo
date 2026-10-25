import base64

from odoo import fields, models, _
from odoo.exceptions import UserError


class EiBankImportWizard(models.TransientModel):
    _name = 'ei.bank.import.wizard'
    _description = 'Import bank statement'

    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', '=', 'bank')]")
    file = fields.Binary('Statement CSV', required=True)
    filename = fields.Char()
    currency_id = fields.Many2one('res.currency', related='journal_id.currency_id')
    opening_balance = fields.Float('Opening balance per statement', required=True, digits=(16, 2))
    closing_balance = fields.Float('Closing balance per statement', required=True, digits=(16, 2))

    def action_import(self):
        batch = self.env['ei.bank.import'].import_file(
            self.journal_id, self.filename, base64.b64decode(self.file), self.opening_balance, self.closing_balance)
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.bank.import', 'res_id': batch.id,
                'view_mode': 'form'}


class EiBankLineWizard(models.TransientModel):
    _name = 'ei.bank.line.wizard'
    _description = 'Review bank lines'

    line_ids = fields.Many2many('ei.bank.import.line')
    decision = fields.Selection([('verify', 'Verify party'), ('unidentified', 'Unidentified (to suspense)'),
                                 ('reject', 'Reject')], required=True, default='verify')
    partner_id = fields.Many2one('res.partner')
    note = fields.Text()

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'ei.bank.import.line':
            res['line_ids'] = [(6, 0, self.env.context.get('active_ids', []))]
        return res

    def action_apply(self):
        self.ensure_one()
        if self.decision == 'verify':
            self.line_ids.action_verify_partner(self.partner_id, self.note)
        elif self.decision == 'unidentified':
            self.line_ids.action_mark_unidentified(self.note)
        else:
            self.line_ids.action_reject(self.note)
        return {'type': 'ir.actions.act_window_close'}


class EiLegacyLinkWizard(models.TransientModel):
    _name = 'ei.legacy.link.wizard'
    _description = 'Link approved legacy code to an existing partner'

    code_id = fields.Many2one('ei.legacy.code', required=True)
    partner_id = fields.Many2one('res.partner', required=True)

    def action_link(self):
        if self.code_id.approved_target_type != 'res_partner':
            raise UserError(_("Only a code approved as contact can be linked to a partner."))
        self.code_id.action_materialise(partner=self.partner_id)
        return {'type': 'ir.actions.act_window_close'}
