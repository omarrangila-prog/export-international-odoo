import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

DATE_FORMATS = ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d-%b-%Y', '%d/%m/%y')
HEAD = {
    'invoice_no': ('invoice no', 'invoice no.', 'invoice number', 'invoice', 'inv no', 'document no', 'doc no'),
    'date': ('date', 'invoice date', 'doc date'),
    'amount': ('amount', 'invoice amount', 'total', 'gross amount', 'net amount'),
    'tax': ('tax', 'tax amount', 'sales tax', 'gst'),
    'contract_ref': ('contract', 'contract no', 'contract ref'),
    'da_ref': ('da', 'da no', 'da ref', 'delivery advice'),
    'quantity': ('quantity', 'qty', 'mtl', 'quantity (mtl)'),
}


def norm_no(s):
    """Invoice numbers are compared case/space/dash-insensitively. Leading zeros are significant."""
    return re.sub(r'[\s\-/_.]+', '', (s or '').upper())


def _dec(s):
    s = (s or '').strip().replace(',', '')
    if not s:
        return None
    neg = s.startswith('(') and s.endswith(')')
    try:
        d = Decimal(s.strip('()'))
    except InvalidOperation:
        raise ValueError('not a number: %r' % s)
    return -d if neg else d


def _date(s):
    for f in DATE_FORMATS:
        try:
            return datetime.strptime((s or '').strip(), f).date()
        except ValueError:
            pass
    raise ValueError('unrecognised date: %r' % s)


def parse_rows(filename, data):
    """-> (rows, errors). CSV or XLSX with a header row; PDFs need OCR which is not configured."""
    if (filename or '').lower().endswith('.pdf'):
        return [], ['PDF statements need OCR, which is not configured. Export the statement to CSV/XLSX.']
    if (filename or '').lower().endswith(('.xlsx', '.xlsm')):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        table = [[('' if c is None else (c.strftime('%Y-%m-%d') if hasattr(c, 'strftime') else str(c))) for c in row]
                 for row in wb.worksheets[0].iter_rows(values_only=True)]
    else:
        table = list(csv.reader(io.StringIO(data.decode('utf-8-sig'), newline='')))
    rows, errors, cols = [], [], None
    for n, row in enumerate(table, start=1):
        if not any((c or '').strip() for c in row):
            continue
        if cols is None:
            head = [c.strip().lower() for c in row]
            cols = {k: next((i for i, h in enumerate(head) if h in names), None) for k, names in HEAD.items()}
            if cols['invoice_no'] is None or cols['amount'] is None:
                return [], ['The statement needs at least "Invoice No" and "Amount" columns.']
            continue
        get = lambda k: row[cols[k]].strip() if cols.get(k) is not None and cols[k] < len(row) else ''
        try:
            rec = {'seq': n, 'invoice_no': get('invoice_no'), 'date': _date(get('date')) if get('date') else False,
                   'amount': _dec(get('amount')), 'tax': _dec(get('tax')) or Decimal(0),
                   'contract_ref': get('contract_ref'), 'da_ref': get('da_ref'),
                   'quantity': _dec(get('quantity')) or Decimal(0)}
            if not rec['invoice_no'] or rec['amount'] is None:
                raise ValueError('missing invoice number or amount')
            rows.append(rec)
        except ValueError as e:
            errors.append('row %d: %s' % (n, e))
    return rows, errors


class EiParentStatement(models.Model):
    _name = 'ei.parent.statement'
    _description = 'Parent-company ledger statement'
    _inherit = ['mail.thread']
    _order = 'date_to desc, id desc'

    name = fields.Char(readonly=True, copy=False, default='New')
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda s: s.env.company.currency_id)
    partner_id = fields.Many2one('res.partner', string='Parent company', required=True, index=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    filename = fields.Char(readonly=True)
    file_sha256 = fields.Char(readonly=True, index=True)
    state = fields.Selection([('imported', 'Imported'), ('classified', 'Exceptions classified'),
                              ('assigned', 'Owners assigned'), ('resolved', 'Resolved'), ('signed', 'Signed off'),
                              ('rejected', 'Rejected import')], default='imported', readonly=True, tracking=True, index=True)
    issues = fields.Text(readonly=True)
    line_ids = fields.One2many('ei.parent.statement.line', 'statement_id')
    n_matched = fields.Integer(compute='_compute_counts')
    n_exceptions = fields.Integer(compute='_compute_counts')
    n_open = fields.Integer(compute='_compute_counts')
    statement_total = fields.Monetary(compute='_compute_counts', currency_field='currency_id')
    internal_total = fields.Monetary(compute='_compute_counts', currency_field='currency_id')
    imported_by = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    signed_by = fields.Many2one('res.users', readonly=True)
    signed_at = fields.Datetime(readonly=True)

    @api.depends('line_ids.status', 'line_ids.resolution_state', 'line_ids.statement_amount', 'line_ids.internal_amount')
    def _compute_counts(self):
        for s in self:
            s.n_matched = len(s.line_ids.filtered(lambda l: l.status == 'matched'))
            exc = s.line_ids.filtered(lambda l: l.status != 'matched')
            s.n_exceptions = len(exc)
            s.n_open = len(exc.filtered(lambda l: l.resolution_state != 'resolved'))
            s.statement_total = sum(s.line_ids.mapped('statement_amount'))
            s.internal_total = sum(s.line_ids.mapped('internal_amount'))

    # ---------------------------------------------------------------- import
    @api.model
    def import_file(self, partner, date_from, date_to, filename, data):
        if not self.env.user.has_group('ei_parent_reconciliation.group_ei_recon_user'):
            raise AccessError(_("Only reconciliation users can import statements."))
        sha = hashlib.sha256(data).hexdigest()
        rows, errors = parse_rows(filename, data)
        dup = self.search([('company_id', '=', self.env.company.id), ('partner_id', '=', partner.id),
                           ('file_sha256', '=', sha), ('state', '!=', 'rejected')], limit=1)
        if dup:
            errors.append(_("This exact file was already imported as %s.", dup.name))
        st = self.create({
            'name': self.env['ir.sequence'].next_by_code('ei.parent.statement'), 'partner_id': partner.id,
            'date_from': date_from, 'date_to': date_to, 'filename': filename, 'file_sha256': sha,
            'issues': '\n'.join(errors) or False, 'state': 'rejected' if errors else 'imported'})
        if not errors:
            self.env['ei.parent.statement.line'].create([{
                'statement_id': st.id, 'sequence': r['seq'], 'invoice_no': r['invoice_no'], 'date': r['date'],
                'statement_amount': float(r['amount']), 'statement_tax': float(r['tax']),
                'contract_ref': r['contract_ref'], 'da_ref': r['da_ref'], 'statement_qty': float(r['quantity']),
                'source': 'statement'} for r in rows])
        return st

    # ----------------------------------------------------------------- match
    def action_match(self):
        """Classify every line. READ-ONLY on accounting: no journal entry is created or edited."""
        Move = self.env['account.move']
        for st in self:
            if st.state not in ('imported', 'classified', 'assigned'):
                raise UserError(_("Statement %s is %s.", st.name, st.state))
            st.line_ids.filtered(lambda l: l.source == 'internal').unlink()
            bills = Move.search([('company_id', '=', st.company_id.id), ('partner_id', '=', st.partner_id.id),
                                 ('move_type', 'in', ('in_invoice', 'in_refund')), ('state', '=', 'posted'),
                                 ('invoice_date', '>=', st.date_from), ('invoice_date', '<=', st.date_to)])
            by_no = {}
            for b in bills:
                by_no.setdefault(norm_no(b.ref), []).append(b)
            used, seen = set(), {}
            cur = st.currency_id
            for l in st.line_ids.filtered(lambda x: x.source == 'statement').sorted('sequence'):
                key = norm_no(l.invoice_no)
                vals = {'internal_move_id': False, 'internal_amount': 0.0, 'internal_tax': 0.0, 'status': 'missing_internal'}
                if key in seen:
                    vals['status'] = 'duplicate'
                else:
                    seen[key] = l
                    cands = [b for b in by_no.get(key, []) if b.id not in used]
                    if cands:
                        b = cands[0]
                        used.add(b.id)
                        sign = 1 if b.move_type == 'in_invoice' else -1
                        vals.update(internal_move_id=b.id, internal_amount=sign * b.amount_total, internal_tax=sign * b.amount_tax)
                        if not cur.is_zero(vals['internal_amount'] - l.statement_amount):
                            vals['status'] = 'amount_difference'
                        elif not cur.is_zero(vals['internal_tax'] - l.statement_tax):
                            vals['status'] = 'tax_difference'
                        else:
                            vals['status'] = 'matched'
                l.write(vals)
            # same amount, different number -> possible match (suggestion only)
            for l in st.line_ids.filtered(lambda x: x.status == 'missing_internal'):
                for b in bills:
                    sign = 1 if b.move_type == 'in_invoice' else -1
                    if b.id not in used and cur.is_zero(sign * b.amount_total - l.statement_amount):
                        l.write({'status': 'possible_match', 'internal_move_id': b.id, 'internal_amount': sign * b.amount_total,
                                 'internal_tax': sign * b.amount_tax})
                        used.add(b.id)
                        break
            for b in bills.filtered(lambda x: x.id not in used):
                sign = 1 if b.move_type == 'in_invoice' else -1
                self.env['ei.parent.statement.line'].create({
                    'statement_id': st.id, 'source': 'internal', 'status': 'missing_supplier', 'invoice_no': b.ref or b.name,
                    'date': b.invoice_date, 'internal_move_id': b.id, 'internal_amount': sign * b.amount_total,
                    'internal_tax': sign * b.amount_tax, 'sequence': 100000 + b.id})
            st.state = 'classified'
            for l in st.line_ids.filtered(lambda x: x.status == 'matched'):
                l.resolution_state = 'resolved'

    def action_check_assigned(self):
        for st in self:
            if st.state != 'classified':
                raise UserError(_("Run the matching first."))
            exc = st.line_ids.filtered(lambda l: l.status != 'matched')
            if exc.filtered(lambda l: not l.owner_id):
                raise UserError(_("Every exception needs an owner."))
            st.state = 'assigned'

    def action_check_resolved(self):
        for st in self:
            if st.state != 'assigned':
                raise UserError(_("Assign owners first."))
            if st.line_ids.filtered(lambda l: l.status != 'matched' and l.resolution_state != 'resolved'):
                raise UserError(_("%s exceptions are still open.", st.n_open))
            st.state = 'resolved'

    def action_sign(self):
        if not self.env.user.has_group('ei_parent_reconciliation.group_ei_recon_approver'):
            raise AccessError(_("Only a reconciliation approver can sign off."))
        for st in self:
            if st.state != 'resolved':
                raise UserError(_("Only a fully resolved statement can be signed."))
            if st.imported_by == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: the importer cannot sign off the statement."))
            st.write({'state': 'signed', 'signed_by': self.env.user.id, 'signed_at': fields.Datetime.now()})

    def write(self, vals):
        if any(r.state == 'signed' for r in self) and set(vals) - {'message_follower_ids'} and not self.env.context.get('ei_system'):
            raise UserError(_("A signed statement is final."))
        return super().write(vals)


class EiParentStatementLine(models.Model):
    _name = 'ei.parent.statement.line'
    _description = 'Parent statement line / exception'
    _inherit = ['mail.thread']
    _order = 'statement_id, sequence'

    statement_id = fields.Many2one('ei.parent.statement', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='statement_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='statement_id.currency_id')
    sequence = fields.Integer()
    source = fields.Selection([('statement', 'On parent statement'), ('internal', 'Only in our books')], default='statement')
    invoice_no = fields.Char(required=True)
    date = fields.Date()
    contract_ref = fields.Char()
    da_ref = fields.Char()
    statement_qty = fields.Float(digits=(16, 3))
    statement_amount = fields.Monetary(currency_field='currency_id')
    statement_tax = fields.Monetary(currency_field='currency_id')
    internal_move_id = fields.Many2one('account.move')
    internal_amount = fields.Monetary(currency_field='currency_id')
    internal_tax = fields.Monetary(currency_field='currency_id')
    difference = fields.Monetary(compute='_compute_difference', store=True, currency_field='currency_id')
    status = fields.Selection([
        ('matched', 'Matched'), ('possible_match', 'Possible match'), ('missing_internal', 'Missing in our books'),
        ('missing_supplier', 'Missing on parent statement'), ('duplicate', 'Duplicate on statement'),
        ('amount_difference', 'Amount difference'), ('tax_difference', 'Tax difference'),
    ], index=True, tracking=True)
    owner_id = fields.Many2one('res.users', tracking=True)
    comment = fields.Text()
    resolution = fields.Selection([
        ('our_correction', 'We correct our records (via normal accounting documents)'),
        ('supplier_correction', 'Parent company to correct'),
        ('timing', 'Timing difference, clears next period'),
        ('accepted', 'Difference accepted by approver'),
        ('duplicate_ignored', 'Duplicate line ignored'),
    ], tracking=True)
    resolution_state = fields.Selection([('open', 'Open'), ('resolved', 'Resolved')], default='open', tracking=True)
    resolved_by = fields.Many2one('res.users', readonly=True)
    adjustment_move_id = fields.Many2one('account.move', string='Adjusting document',
                                         help="Credit note / bill created through normal accounting; never an edit of a posted entry.")

    @api.depends('statement_amount', 'internal_amount')
    def _compute_difference(self):
        for l in self:
            l.difference = l.statement_amount - l.internal_amount

    def action_assign(self, user):
        for l in self:
            if l.statement_id.state in ('signed', 'rejected'):
                raise UserError(_("The statement is %s.", l.statement_id.state))
            l.owner_id = user

    def action_resolve(self, resolution, comment):
        for l in self:
            if l.statement_id.state in ('signed', 'rejected'):
                raise UserError(_("The statement is %s.", l.statement_id.state))
            if l.status == 'matched':
                continue
            if not (comment or '').strip():
                raise UserError(_("Write a comment to resolve %s.", l.invoice_no))
            if l.owner_id != self.env.user and not self.env.user.has_group('ei_parent_reconciliation.group_ei_recon_approver'):
                raise AccessError(_("Only the owner or an approver can resolve this exception."))
            if resolution == 'accepted' and not self.env.user.has_group('ei_parent_reconciliation.group_ei_recon_approver'):
                raise AccessError(_("Only an approver can accept a difference."))
            if resolution == 'duplicate_ignored' and l.status != 'duplicate':
                raise UserError(_("Only a duplicate line can be ignored."))
            if resolution == 'our_correction' and not l.adjustment_move_id and l.status in ('amount_difference', 'tax_difference'):
                raise UserError(_("Link the adjusting accounting document (credit note or bill) first."))
            l.write({'resolution': resolution, 'comment': comment, 'resolution_state': 'resolved',
                     'resolved_by': self.env.user.id})
