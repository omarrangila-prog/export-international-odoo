"""Invoice cutting: what each customer wants on its invoice, and a log of every output (PDF, email/print, spreadsheet).

The log answers "which version did the customer get?": each output records the invoice's state, total and a fingerprint of its lines;
when the fingerprint changes between two outputs, the later one is a new revision. A draft can be previewed and edited before it is
posted; an output of a draft is marked as a draft, never as an issued invoice."""
import base64
import hashlib
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ei_invoice_grouping = fields.Selection([('per_lifting', 'One line per truck loading'), ('per_da', 'One line per DA and material')],
                                           'Invoice lines', default='per_lifting',
                                           help="How this customer wants the delivered material laid out on its invoices.")
    ei_show_hs_code = fields.Boolean('Show HS code on invoice lines',
                                     help="Taken from the supplier invoice recorded on the Daily Order Request.")
    ei_show_contract_ref = fields.Boolean("Show the parent's contract reference on invoice lines")
    ei_invoice_note = fields.Text('Note printed on every invoice', help="e.g. the customer's purchase-order wording or bank details they asked for.")


class EiInvoiceOutput(models.Model):
    _name = 'ei.invoice.output'
    _description = 'Invoice output (PDF, email, spreadsheet)'
    _order = 'id desc'

    move_id = fields.Many2one('account.move', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='move_id.company_id', store=True, index=True)
    partner_id = fields.Many2one(related='move_id.partner_id', store=True)
    kind = fields.Selection([('pdf', 'PDF printed'), ('send', 'Sent / printed from Send'), ('excel', 'Spreadsheet')], required=True)
    move_state = fields.Char('Invoice state then', required=True)
    amount_total = fields.Monetary('Total then', currency_field='currency_id')
    currency_id = fields.Many2one(related='move_id.currency_id')
    fingerprint = fields.Char(required=True)
    revision = fields.Integer(required=True)
    user_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user)
    at = fields.Datetime(required=True, default=fields.Datetime.now)

    def write(self, vals):
        raise UserError(_("The output log cannot be changed."))


class AccountMove(models.Model):
    _inherit = 'account.move'

    ei_output_ids = fields.One2many('ei.invoice.output', 'move_id', string='Outputs')
    ei_revision = fields.Integer('Revision given to the customer', compute='_compute_ei_revision')

    @api.depends('ei_output_ids')
    def _compute_ei_revision(self):
        for m in self:
            m.ei_revision = max(m.ei_output_ids.mapped('revision') or [0])

    def _ei_fingerprint(self):
        self.ensure_one()
        rows = [(l.name or '', l.quantity, l.price_unit, l.price_subtotal) for l in self.invoice_line_ids.sorted('id')]
        return hashlib.sha256(repr((self.partner_id.id, self.invoice_date and str(self.invoice_date), rows, self.amount_total)).encode()).hexdigest()

    def _ei_log_output(self, kind):
        Out = self.env['ei.invoice.output'].sudo()
        for m in self.filtered(lambda x: x.is_sale_document(include_receipts=False)):
            fp = m._ei_fingerprint()
            last = Out.search([('move_id', '=', m.id)], limit=1)
            Out.create({'move_id': m.id, 'kind': kind, 'move_state': m.state, 'amount_total': m.amount_total, 'fingerprint': fp,
                        'revision': (last.revision if last and last.fingerprint == fp else (last.revision + 1 if last else 1)),
                        'user_id': self.env.user.id})

    def action_print_pdf(self):
        res = super().action_print_pdf()
        self._ei_log_output('pdf')
        return res

    def action_ei_export_excel(self):
        """The invoice as a spreadsheet, for customers who ask for one. A draft is labelled DRAFT on the sheet."""
        self.ensure_one()
        import xlsxwriter
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        ws = wb.add_worksheet('Invoice')
        bold, money = wb.add_format({'bold': True}), wb.add_format({'num_format': '#,##0.00'})
        head = [(_("Invoice"), self.name if self.state == 'posted' else _("DRAFT - not issued")), (_("Customer"), self.partner_id.display_name),
                (_("Date"), str(self.invoice_date or '')), (_("Reference"), self.ref or '')]
        for r, (k, v) in enumerate(head):
            ws.write(r, 0, k, bold)
            ws.write(r, 1, v)
        r = len(head) + 1
        for c, h in enumerate((_("Description"), _("Quantity"), _("Unit price"), _("Amount"))):
            ws.write(r, c, h, bold)
        for l in self.invoice_line_ids.filtered(lambda x: x.display_type == 'product'):
            r += 1
            ws.write(r, 0, l.name or '')
            ws.write_number(r, 1, l.quantity)
            ws.write_number(r, 2, l.price_unit, money)
            ws.write_number(r, 3, l.price_subtotal, money)
        r += 2
        for k, v in ((_("Untaxed"), self.amount_untaxed), (_("Tax"), self.amount_tax), (_("Total"), self.amount_total)):
            ws.write(r, 2, k, bold)
            ws.write_number(r, 3, v, money)
            r += 1
        if self.partner_id.ei_invoice_note:
            ws.write(r + 1, 0, self.partner_id.ei_invoice_note)
        ws.set_column(0, 0, 60)
        ws.set_column(1, 3, 16)
        wb.close()
        name = '%s.xlsx' % (self.name if self.state == 'posted' else 'DRAFT-%s' % self.id).replace('/', '-')
        att = self.env['ir.attachment'].create({'name': name, 'raw': buf.getvalue(), 'res_model': self._name, 'res_id': self.id,
                                                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
        self._ei_log_output('excel')
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s?download=true' % att.id, 'target': 'download'}


class AccountMoveSendWizard(models.TransientModel):
    _inherit = 'account.move.send.wizard'

    def action_send_and_print(self, allow_fallback_pdf=False):
        res = super().action_send_and_print(allow_fallback_pdf=allow_fallback_pdf)
        self.move_id._ei_log_output('send')
        return res
