"""R9: the old FoxPro system against Odoo.

An extract is produced OUTSIDE Odoo by `migration/foxpro_extract.py` on a copy of the FoxPro folder (read-only, every file hashed).
Its manifest is recorded here: one row per table with code page, record and deleted counts, so a later extract shows exactly which
tables changed. Control totals typed from the old system's own reports (record counts, trial balance, bank balances, receivables,
payables, any account) are compared with the books at the cut-off date. A second person signs each comparison. Nothing is posted.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

FORMAT = 'ei-foxpro-extract/1'


class EiMigrationExtract(models.Model):
    _name = 'ei.migration.extract'
    _description = 'Old system (FoxPro) extract'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    manifest_sha256 = fields.Char(readonly=True, index=True)
    source_files = fields.Integer('Files in the FoxPro folder', readonly=True)
    table_ids = fields.One2many('ei.migration.table', 'extract_id', readonly=True)
    n_tables = fields.Integer('Tables', compute='_compute_totals')
    n_records = fields.Integer('Records found', compute='_compute_totals')
    n_deleted = fields.Integer('Marked deleted', compute='_compute_totals')
    n_changed = fields.Integer('Tables changed since the previous extract', compute='_compute_totals')
    problems = fields.Text(readonly=True)
    previous_id = fields.Many2one('ei.migration.extract', readonly=True)
    imported_by = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    imported_at = fields.Datetime(readonly=True, default=fields.Datetime.now)

    @api.depends('table_ids.records_found', 'table_ids.deleted', 'table_ids.changed')
    def _compute_totals(self):
        for r in self:
            r.n_tables = len(r.table_ids)
            r.n_records = sum(r.table_ids.mapped('records_found'))
            r.n_deleted = sum(r.table_ids.mapped('deleted'))
            r.n_changed = len(r.table_ids.filtered('changed'))

    @api.model
    def record_manifest(self, data, filename='manifest.json'):
        if not self.env.user.has_group('account.group_account_user') and not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_("Only accounting staff record old-system extracts."))
        sha = hashlib.sha256(data).hexdigest()
        same = self.search([('company_id', '=', self.env.company.id), ('manifest_sha256', '=', sha)], limit=1)
        if same:
            return same                                              # the same extract recorded twice is one extract
        try:
            m = json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise UserError(_("%s is not a manifest written by foxpro_extract.py.", filename))
        if not isinstance(m, dict) or m.get('format') != FORMAT or not isinstance(m.get('tables'), list):
            raise UserError(_("%s is not a manifest written by foxpro_extract.py.", filename))
        prev = self.search([('company_id', '=', self.env.company.id)], limit=1)
        old = {t.file: t.sha256 for t in prev.table_ids}
        ext = self.create({
            'name': _("Extract %s", fields.Datetime.now().strftime('%Y-%m-%d %H:%M')), 'manifest_sha256': sha,
            'source_files': len(m.get('source_files') or {}), 'previous_id': prev.id or False,
            'problems': '\n'.join('%s: %s' % (p.get('file'), p.get('problem')) for p in m.get('problems') or []) or False})
        self.env['ei.migration.table'].sudo().create([{
            'extract_id': ext.id, 'file': t['file'], 'sha256': t.get('sha256'), 'version': t.get('version'), 'codepage': t.get('codepage'),
            'codepage_known': bool(t.get('codepage_known')), 'records_in_header': int(t.get('records_in_header') or 0),
            'records_found': int(t.get('records_found') or 0), 'deleted': int(t.get('deleted') or 0),
            'fields_json': json.dumps(t.get('fields') or []), 'n_fields': len(t.get('fields') or []),
            'memo_missing': bool((t.get('memo') or {}).get('missing')),
            'changed': bool(prev) and old.get(t['file']) != t.get('sha256'),
        } for t in m['tables']])
        ext.sudo().message_post(body=_("Recorded from %(f)s: %(t)s tables, %(r)s records (%(d)s marked deleted).",
                                f=filename, t=ext.n_tables, r=ext.n_records, d=ext.n_deleted))
        return ext


class EiMigrationTable(models.Model):
    _name = 'ei.migration.table'
    _description = 'Table in an old-system extract'
    _order = 'extract_id, file'

    extract_id = fields.Many2one('ei.migration.extract', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='extract_id.company_id', store=True)
    file = fields.Char(required=True)
    sha256 = fields.Char()
    version = fields.Char()
    codepage = fields.Char()
    codepage_known = fields.Boolean()
    records_in_header = fields.Integer()
    records_found = fields.Integer()
    deleted = fields.Integer('Marked deleted')
    live = fields.Integer('Not deleted', compute='_compute_live')
    n_fields = fields.Integer('Fields')
    fields_json = fields.Text('Field list')
    memo_missing = fields.Boolean()
    changed = fields.Boolean('Changed since the previous extract')

    @api.depends('records_found', 'deleted')
    def _compute_live(self):
        for t in self:
            t.live = t.records_found - t.deleted


class EiMigrationControl(models.Model):
    _name = 'ei.migration.control'
    _description = 'Old-system control total against the books'
    _inherit = ['mail.thread']
    _order = 'cutoff desc, id'

    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    cutoff = fields.Date('Cut-off date', required=True)
    kind = fields.Selection([
        ('table_count', 'Record count of a table'), ('tb_debits', 'Trial balance: total debits'), ('account', 'Balance of one account'),
        ('bank', 'Bank account balance'), ('receivable', 'Customers owe us (receivable total)'), ('payable', 'We owe suppliers (payable total)'),
    ], required=True)
    label = fields.Char('As printed on the old report', required=True)
    legacy_value = fields.Char('Old system figure', required=True, help="Typed exactly as printed, e.g. 1,234,567.89 or (5,000.00).")
    table_id = fields.Many2one('ei.migration.table')
    deleted_rule = fields.Selection([('live', 'Count without deleted records'), ('all', 'Count every record')], default='live',
                                    help="FoxPro keeps deleted records until the file is packed. Say which way the old report counts.")
    account_id = fields.Many2one('account.account')
    journal_id = fields.Many2one('account.journal', domain="[('type', 'in', ('bank', 'cash'))]")
    odoo_value = fields.Float('In Odoo', compute='_compute_compare', digits=(16, 3))
    difference = fields.Float('Old less Odoo', compute='_compute_compare', digits=(16, 3))
    status = fields.Selection([('agrees', 'Agrees'), ('differs', 'Differs'), ('unreadable', 'Old figure not a number'), ('incomplete', 'Choose what to compare')],
                              compute='_compute_compare')
    note = fields.Text('Explanation')
    entered_by = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    signed_by = fields.Many2one('res.users', readonly=True, tracking=True)
    signed_at = fields.Datetime(readonly=True)

    @staticmethod
    def _parse(text):
        s = (text or '').strip().replace(',', '').replace(' ', '')
        neg = s.startswith('(') and s.endswith(')') or s.endswith('-') or s.endswith('CR')
        s = s.strip('()').rstrip('-').removesuffix('CR').removesuffix('DR')
        try:
            v = Decimal(s)
        except InvalidOperation:
            return None
        return -v if neg else v

    def _books(self):
        self.ensure_one()
        AML = self.env['account.move.line'].sudo()
        base = [('company_id', '=', self.company_id.id), ('parent_state', '=', 'posted'), ('date', '<=', self.cutoff)]
        if self.kind == 'table_count':
            if not self.table_id:
                return None
            return self.table_id.live if self.deleted_rule == 'live' else self.table_id.records_found
        if self.kind == 'tb_debits':
            return AML._read_group(base, [], ['debit:sum'])[0][0] or 0.0
        if self.kind == 'account':
            return AML._read_group(base + [('account_id', '=', self.account_id.id)], [], ['balance:sum'])[0][0] or 0.0 if self.account_id else None
        if self.kind == 'bank':
            return self.journal_id.sudo()._ei_ledger_balance(self.cutoff) if self.journal_id else None
        t = 'asset_receivable' if self.kind == 'receivable' else 'liability_payable'
        bal = AML._read_group(base + [('account_id.account_type', '=', t)], [], ['balance:sum'])[0][0] or 0.0
        return bal if self.kind == 'receivable' else -bal

    @api.depends('kind', 'legacy_value', 'table_id', 'deleted_rule', 'account_id', 'journal_id', 'cutoff')
    def _compute_compare(self):
        for r in self:
            legacy, books = r._parse(r.legacy_value), (r._books() if r.cutoff and r.kind else None)
            r.odoo_value = books or 0.0
            if books is None:
                r.status, r.difference = 'incomplete', 0.0
            elif legacy is None:
                r.status, r.difference = 'unreadable', 0.0
            else:
                r.difference = float(legacy - Decimal(str(books)))
                r.status = 'agrees' if abs(r.difference) < 0.005 else 'differs'

    def write(self, vals):
        if any(r.signed_by for r in self) and set(vals) - {'message_follower_ids', 'message_main_attachment_id'} and not self.env.context.get('ei_system'):
            raise UserError(_("A signed comparison is final. Enter a new one."))
        return super().write(vals)

    def unlink(self):
        if any(r.signed_by for r in self):
            raise UserError(_("A signed comparison is kept as evidence."))
        return super().unlink()

    def action_sign(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_("Only an accounting manager signs migration comparisons."))
        for r in self:
            if r.signed_by:
                continue
            if r.status in ('incomplete', 'unreadable'):
                raise UserError(_("%s: the comparison is not complete.", r.label))
            if r.entered_by == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: the person who typed the old figure cannot sign it."))
            if r.status == 'differs' and not (r.note or '').strip():
                raise UserError(_("%(l)s differs by %(d)s. Explain the difference before signing.", l=r.label, d=r.difference))
            r.with_context(ei_system=True).write({'signed_by': self.env.user.id, 'signed_at': fields.Datetime.now()})


class EiMigrationImportWizard(models.TransientModel):
    _name = 'ei.migration.import.wizard'
    _description = 'Record an old-system extract'

    file = fields.Binary('manifest.json', required=True)
    filename = fields.Char()

    def action_import(self):
        from odoo.addons.ei_legacy_master.models.parsing import upload_bytes
        ext = self.env['ei.migration.extract'].record_manifest(upload_bytes(self.file), self.filename or 'manifest.json')
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.migration.extract', 'res_id': ext.id, 'views': [(False, 'form')]}
