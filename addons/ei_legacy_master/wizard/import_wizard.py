import base64

from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError

from ..models.legacy_code import TARGET_TYPES


class EiImportWizard(models.TransientModel):
    _name = 'ei.import.wizard'
    _description = 'Import legacy code list'

    file = fields.Binary('CODE LIST (.xlsx) or normalised CSV', required=True)
    filename = fields.Char()

    def action_import(self):
        if not self.env.user.has_group('ei_legacy_master.group_ei_importer'):
            raise AccessError(_("Only legacy-code importers can run an import."))
        batch = self.env['ei.import.batch'].import_file(self.filename, base64.b64decode(self.file))
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.import.batch', 'res_id': batch.id,
                'views': [(False, 'form')], 'target': 'current'}


class EiApproveWizard(models.TransientModel):
    _name = 'ei.legacy.code.approve.wizard'
    _description = 'Approve / reject legacy code mappings'

    code_ids = fields.Many2many('ei.legacy.code', string='Codes')
    decision = fields.Selection([('approve', 'Approve'), ('reject', 'Reject')], default='approve', required=True)
    target_type = fields.Selection(TARGET_TYPES, string='Approved target')
    note = fields.Text()

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ids = self.env.context.get('active_ids') or []
        if self.env.context.get('active_model') == 'ei.legacy.code' and ids:
            res['code_ids'] = [(6, 0, ids)]
        return res

    def action_apply(self):
        self.ensure_one()
        if not self.code_ids:
            raise UserError(_("Select at least one code."))
        if self.decision == 'approve':
            if not self.target_type:
                raise UserError(_("Choose the approved target type."))
            self.code_ids.action_approve(self.target_type, self.note)
        else:
            self.code_ids.action_reject(self.note)
        return {'type': 'ir.actions.act_window_close'}
