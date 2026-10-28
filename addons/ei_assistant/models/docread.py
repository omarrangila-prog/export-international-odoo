"""Reading supplier invoices and parent statements from their PDF or picture, with the language model approved for Ask
(open decision 36, approved 27 Oct 2026). Off whenever Ask's language model is off.

What it reads is a PROPOSAL. A supplier invoice proposal is shown beside the record and fills only empty fields, and only when a person
presses "Use these values"; the invoice is then checked exactly as a typed one (contract, DA, rates, quantities, HS code).
For a parent statement, the rows read from a PDF are imported like a CSV. Its sign-off still needs the total printed on the statement,
typed by a person, to equal the rows. Nothing is ever posted from what the model read.
"""
import base64
import csv
import io
import json

from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError

MAX_BYTES = 20 * 1024 * 1024
KINDS = {'application/pdf': 'document', 'image/png': 'image', 'image/jpeg': 'image', 'image/webp': 'image', 'image/gif': 'image'}

INVOICE_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['invoice_number', 'invoice_date', 'supplier_name', 'total', 'tax', 'lines', 'unclear'],
    'properties': {
        'invoice_number': {'type': 'string', 'description': "exactly as printed; empty if not visible"},
        'invoice_date': {'type': 'string', 'description': "YYYY-MM-DD; empty if not visible"},
        'supplier_name': {'type': 'string'},
        'total': {'type': 'string', 'description': "grand total as printed, digits only with a decimal point; empty if not visible"},
        'tax': {'type': 'string', 'description': "total sales tax as printed; empty if not visible"},
        'lines': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['description', 'da_reference', 'quantity_mtl', 'rate_per_mtl', 'hs_code'],
            'properties': {'description': {'type': 'string'}, 'da_reference': {'type': 'string', 'description': "delivery advice number if printed"},
                           'quantity_mtl': {'type': 'string'}, 'rate_per_mtl': {'type': 'string'}, 'hs_code': {'type': 'string'}}}},
        'unclear': {'type': 'array', 'items': {'type': 'string'}, 'description': "anything hard to read or ambiguous, in plain words"},
    },
}
STATEMENT_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['rows', 'printed_total', 'unclear'],
    'properties': {
        'rows': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['invoice_no', 'date', 'amount', 'tax', 'hs_code', 'quantity'],
            'properties': {'invoice_no': {'type': 'string'}, 'date': {'type': 'string', 'description': "YYYY-MM-DD"},
                           'amount': {'type': 'string', 'description': "signed: a credit shown in brackets or with CR is negative"},
                           'tax': {'type': 'string'}, 'hs_code': {'type': 'string'}, 'quantity': {'type': 'string'}}}},
        'printed_total': {'type': 'string', 'description': "the statement's own grand total as printed; empty if none"},
        'unclear': {'type': 'array', 'items': {'type': 'string'}},
    },
}
INSTRUCTIONS = ("Copy what is printed on this document into the JSON fields. Copy numbers and codes exactly as printed (keep leading zeros, "
                "keep the document's own numbering); write amounts as plain numbers with a decimal point and no thousands separators. "
                "Never guess or calculate a value that is not printed: leave it empty and say so under 'unclear'.")


class EiAssistant(models.AbstractModel):
    _inherit = 'ei.assistant'

    def _docread(self, name, mime, data, schema, task):
        """-> dict read from the document by the language model, or raises UserError in plain words."""
        if not self._llm_available():
            raise UserError(_("Reading documents automatically is not switched on. Enter the values by hand; nothing is guessed."))
        if mime not in KINDS:
            raise UserError(_("%s is not a PDF or a picture.", name))
        data = bytes(getattr(data, 'content', data) or b'')      # Odoo 20 hands attachments back as a lazy binary value
        if not data or len(data) > MAX_BYTES:
            raise UserError(_("%s is empty or larger than 20 MB.", name))
        block = {'type': KINDS[mime], 'source': {'type': 'base64', 'media_type': mime, 'data': base64.standard_b64encode(data).decode()}}
        client, sdk = self._llm_client(), self._llm_sdk()
        try:
            resp = client.beta.messages.create(
                model=self._llm_param('ei_assistant.llm_model', 'claude-opus-5-5'), max_tokens=16000,
                messages=[{'role': 'user', 'content': [block, {'type': 'text', 'text': task + '\n\n' + INSTRUCTIONS}]}],
                output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': schema}},
                betas=['server-side-fallback-2026-07-01'], fallbacks='default')
        except (sdk.APIStatusError, sdk.APIConnectionError):
            raise UserError(_("The document could not be read just now. Try again later, or enter the values by hand."))
        if resp.stop_reason in ('refusal', 'max_tokens'):
            raise UserError(_("The document could not be read completely. Enter the values by hand."))
        text = next((b.text for b in resp.content if b.type == 'text'), '')
        try:
            return json.loads(text)
        except ValueError:
            raise UserError(_("The document could not be read completely. Enter the values by hand."))


class EiSupplierIntake(models.Model):
    _inherit = 'ei.supplier.intake'

    ai_proposal = fields.Json('Read from the document', readonly=True, copy=False)
    ai_proposal_html = fields.Html('Read from the document', compute='_compute_ai_proposal_html', sanitize=False)

    def _compute_ocr_status(self):
        on = self.env['ei.assistant']._llm_available()
        for r in self:
            r.ocr_status = _("Reading the attached invoice is switched on: press Read the document; you check and apply what it proposes.") if on else \
                _("OCR provider not configured - enter the invoice manually")

    @api.depends('ai_proposal')
    def _compute_ai_proposal_html(self):
        for r in self:
            p = r.ai_proposal
            if not p:
                r.ai_proposal_html = False
                continue
            head = Markup('<p class="text-muted">%s</p><p>%s</p>') % (
                _("Read by a language model from the attached document. Nothing has been changed; check it against the paper."),
                Markup(' &middot; ').join(Markup('<b>%s</b> %s') % (k, escape(v or '-')) for k, v in (
                    (_("Invoice no."), p.get('invoice_number')), (_("Date"), p.get('invoice_date')), (_("Supplier"), p.get('supplier_name')),
                    (_("Total"), p.get('total')), (_("Tax"), p.get('tax')))))
            rows = Markup('').join(Markup('<tr><td>%s</td><td>%s</td><td class="text-end">%s</td><td class="text-end">%s</td><td>%s</td></tr>') % (
                l.get('description'), l.get('da_reference'), l.get('quantity_mtl'), l.get('rate_per_mtl'), l.get('hs_code')) for l in p.get('lines') or [])
            table = Markup('<table class="table table-sm"><thead><tr><th>%s</th><th>%s</th><th class="text-end">%s</th><th class="text-end">%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table>') % (
                _("Line"), _("DA"), _("MTL"), _("Rate / MTL"), _("HS code"), rows) if rows else Markup('')
            unclear = Markup('<p class="text-warning">%s %s</p>') % (_("Unclear:"), '; '.join(p['unclear'])) if p.get('unclear') else Markup('')
            r.ai_proposal_html = head + table + unclear

    def action_ocr(self):
        self.ensure_one()
        if self.state not in ('draft', 'mismatch'):
            raise UserError(_("Only an invoice not yet checked can be read again."))
        att = self.env['ir.attachment'].search([('res_model', '=', self._name), ('res_id', '=', self.id),
                                                ('mimetype', 'in', list(KINDS))], order='id desc', limit=1)
        if not att:
            if not self.env['ei.assistant']._llm_available():
                return super().action_ocr()
            raise UserError(_("Attach the supplier's invoice (PDF or picture) first."))
        data = self.env['ei.assistant']._docread(att.name, att.mimetype, att.raw, INVOICE_SCHEMA, _("This is a supplier invoice for steel sold in metric tons (MTL)."))
        self.with_context(ei_system=True).ai_proposal = data
        self.message_post(body=_("%s was read by the language model. Nothing was changed until someone applies it.", att.name))
        return True

    def action_ai_apply(self):
        """Fill EMPTY fields from the proposal and add lines whose DA is recognised; then the normal check decides."""
        self.ensure_one()
        p = self.ai_proposal or {}
        if self.state not in ('draft', 'mismatch') or not p:
            raise UserError(_("There is nothing to apply."))
        vals, skipped = {}, []
        if not self.invoice_number and p.get('invoice_number'):
            vals['invoice_number'] = p['invoice_number']
        if not self.invoice_date and p.get('invoice_date'):
            vals['invoice_date'] = p['invoice_date']
        for key, field in (('total', 'stated_total'), ('tax', 'stated_tax')):
            if not self[field] and p.get(key):
                try:
                    vals[field] = float(p[key])
                except ValueError:
                    skipped.append(_("%(f)s %(v)r is not a number", f=key, v=p[key]))
        DAL = self.env['ei.da.line']
        lines = []
        for l in p.get('lines') or []:
            da_line = DAL.search([('da_id.name', '=', (l.get('da_reference') or '').strip()), ('state', 'in', ('approved', 'fulfilled')),
                                  ('da_id.parent_partner_id', '=', self.partner_id.id)], limit=1) if l.get('da_reference') else DAL
            if not da_line:
                skipped.append(_("line %(d)r: DA %(r)r not found for this supplier", d=l.get('description'), r=l.get('da_reference')))
                continue
            try:
                lines.append({'intake_id': self.id, 'da_line_id': da_line.id, 'received_mtl': float(l['quantity_mtl']),
                              'unit_rate': float(l['rate_per_mtl']), 'hs_code': (l.get('hs_code') or '').strip() or False})
            except (ValueError, KeyError, TypeError):
                skipped.append(_("line %r: quantity or rate is not a number", l.get('description')))
        if vals:
            self.write(vals)
        if lines and not self.line_ids:
            self.env['ei.supplier.intake.line'].create(lines)
        elif lines:
            skipped.append(_("the invoice already has lines; proposed lines were not added"))
        self.message_post(body=_("Values read from the document were applied by %(u)s.%(s)s", u=self.env.user.name,
                                 s=(' ' + _("Not applied: %s.", '; '.join(skipped))) if skipped else ''))
        return True


class EiParentStatement(models.Model):
    _inherit = 'ei.parent.statement'

    @api.model
    def import_file(self, partner, date_from, date_to, filename, data, control_total=None):
        """A PDF statement is read into rows by the language model when it is switched on; everything after that is the CSV path."""
        if not (filename or '').lower().endswith('.pdf') or not self.env['ei.assistant']._llm_available():
            return super().import_file(partner, date_from, date_to, filename, data, control_total=control_total)
        read = self.env['ei.assistant']._docread(filename, 'application/pdf', data, STATEMENT_SCHEMA, _("This is a parent company's ledger statement listing invoices and credit notes."))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Invoice No', 'Date', 'Amount', 'Tax', 'HS Code', 'Quantity'])
        for r in read.get('rows') or []:
            w.writerow([r.get('invoice_no'), r.get('date'), r.get('amount'), r.get('tax') or '0', r.get('hs_code'), r.get('quantity') or '0'])
        st = super().import_file(partner, date_from, date_to, filename[:-4] + ' (read from PDF).csv', buf.getvalue().encode(), control_total=control_total)
        self.env['ir.attachment'].create({'name': filename, 'raw': data, 'mimetype': 'application/pdf', 'res_model': st._name, 'res_id': st.id})
        note = _("Rows were read from %(f)s by a language model. The statement's own printed total reads %(t)s; sign-off needs the total typed by a person "
                 "to equal the imported rows.", f=filename, t=read.get('printed_total') or _("(not found)"))
        if read.get('unclear'):
            note += ' ' + _("Unclear: %s", '; '.join(read['unclear']))
        st.message_post(body=note)
        return st
