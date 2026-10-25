import base64

from odoo import fields, models


class EiParentImportWizard(models.TransientModel):
    _name = 'ei.parent.import.wizard'
    _description = 'Import parent statement'

    partner_id = fields.Many2one('res.partner', string='Parent company', required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    file = fields.Binary(required=True)
    filename = fields.Char()

    def action_import(self):
        st = self.env['ei.parent.statement'].import_file(self.partner_id, self.date_from, self.date_to, self.filename,
                                                          base64.b64decode(self.file))
        if st.state != 'rejected':
            st.action_match()
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.parent.statement', 'res_id': st.id, 'views': [(False, 'form')]}
