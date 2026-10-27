from odoo import fields, models
from odoo.addons.ei_legacy_master.models.parsing import upload_bytes


class EiParentImportWizard(models.TransientModel):
    _name = 'ei.parent.import.wizard'
    _description = 'Import parent statement'

    partner_id = fields.Many2one('res.partner', string='Parent company', required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    file = fields.Binary(required=True)
    filename = fields.Char()
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    control_total = fields.Monetary("Total printed on the statement", currency_field='currency_id',
                                    help="Type the statement's grand total from the paper or PDF. It proves every row was imported.")

    def action_import(self):
        st = self.env['ei.parent.statement'].import_file(self.partner_id, self.date_from, self.date_to, self.filename,
                                                          upload_bytes(self.file), control_total=self.control_total or None)
        if st.state != 'rejected':
            st.action_match()
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.parent.statement', 'res_id': st.id, 'views': [(False, 'form')]}
