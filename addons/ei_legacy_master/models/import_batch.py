import base64
import csv
import io

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from . import parsing


class EiImportBatch(models.Model):
    _name = 'ei.import.batch'
    _description = 'Legacy code import batch'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True, copy=False, default=lambda s: _('New'))
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda s: s.env.company)
    filename = fields.Char(readonly=True)
    file_sha256 = fields.Char('File SHA-256', readonly=True)
    state = fields.Selection([
        ('failed', 'Rejected - nothing imported'),
        ('imported', 'Imported'),
        ('signed', 'Signed'),
    ], required=True, readonly=True, default='imported', tracking=True)
    imported_by = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    imported_at = fields.Datetime(readonly=True, default=fields.Datetime.now)
    signed_by = fields.Many2one('res.users', readonly=True)
    signed_at = fields.Datetime(readonly=True)
    error_log = fields.Text(readonly=True)
    formula_cells = fields.Integer('Formula-like cells', readonly=True)
    total_expected = fields.Integer(readonly=True)
    total_rows = fields.Integer('Rows in file', readonly=True)
    total_created = fields.Integer(readonly=True)
    total_unchanged = fields.Integer(readonly=True)
    total_changed = fields.Integer('Changed vs master (diffs logged)', readonly=True)
    total_skipped = fields.Integer(readonly=True)
    sheet_ids = fields.One2many('ei.import.batch.sheet', 'batch_id', readonly=True)
    diff_ids = fields.One2many('ei.import.diff', 'batch_id', readonly=True)
    code_ids = fields.One2many('ei.legacy.code', 'batch_id', string='Codes first imported here', readonly=True)

    # ------------------------------------------------------------------ import
    @api.model
    def import_file(self, filename, data):
        """Parse + validate + load. All-or-nothing: any validation error creates a 'failed'
        batch holding the audit trail and imports no codes. Re-running is idempotent."""
        res = parsing.parse(filename, data)
        batch = self.create({
            'name': _('IMP/%s', fields.Datetime.now().strftime('%Y%m%d-%H%M%S')),
            'filename': filename,
            'file_sha256': res.sha256,
            'formula_cells': res.formula_cells,
            'total_expected': parsing.EXPECTED_TOTAL,
            'total_rows': len(res.rows),
            'total_skipped': len(res.skipped),
            'error_log': '\n'.join(res.errors),
            'state': 'imported' if res.ok else 'failed',
        })
        stats = {k: dict(created=0, unchanged=0, changed=0) for k in parsing.EXPECTED_COUNTS}
        if res.ok:
            Code = self.env['ei.legacy.code']
            existing = {(c.source_sheet_key, c.legacy_code): c for c in Code.search(
                [('company_id', '=', batch.company_id.id)])}
            now = fields.Datetime.now()
            for r in res.rows:
                st = stats[r['sheet_key']]
                rec = existing.get((r['sheet_key'], r['code']))
                if not rec:
                    Code.create(Code._values_from_row(r, batch))
                    st['created'] += 1
                    continue
                rec.sudo().with_context(ei_system_write=True).write({'last_sync': now, 'last_batch_id': batch.id})
                diffs = [
                    (label, old, new) for label, old, new in (
                        ('NAME', rec.original_name, r['name']),
                        ('NICK', rec.nickname or '', r['nick']),
                        ('Excel row', str(rec.source_row), str(r['row'])),
                    ) if old != new]
                for label, old, new in diffs:
                    self.env['ei.import.diff'].create({
                        'batch_id': batch.id, 'code_id': rec.id, 'field_label': label,
                        'old_value': old, 'new_value': new})
                st['changed' if diffs else 'unchanged'] += 1
        for sk, expected in parsing.EXPECTED_COUNTS.items():
            actual = sum(1 for r in res.rows if r['sheet_key'] == sk)
            self.env['ei.import.batch.sheet'].create({
                'batch_id': batch.id, 'sheet_key': sk, 'expected': expected, 'actual': actual,
                'missing_nick': sum(1 for r in res.rows if r['sheet_key'] == sk and not r['nick']),
                'duplicates': sum(1 for d in res.duplicates if d[0] == sk),
                **stats[sk]})
        batch.write({
            'total_created': sum(s['created'] for s in stats.values()),
            'total_unchanged': sum(s['unchanged'] for s in stats.values()),
            'total_changed': sum(s['changed'] for s in stats.values()),
        })
        return batch

    # -------------------------------------------------------------------- sign
    def action_sign(self):
        self.ensure_one()
        if not self.env.user.has_group('ei_legacy_master.group_ei_mapping_approver'):
            raise AccessError(_("Only a mapping approver can sign a migration batch."))
        if self.state != 'imported':
            raise UserError(_("Only an imported batch can be signed."))
        if any(not s.counts_ok for s in self.sheet_ids) or self.error_log:
            raise UserError(_("Sheet counts do not match the expected totals; cannot sign."))
        if self.total_changed:
            raise UserError(_("Review the %s logged diffs against the master before signing.", self.total_changed))
        self.write({'state': 'signed', 'signed_by': self.env.user.id, 'signed_at': fields.Datetime.now()})

    # ------------------------------------------------------ reconciliation csv
    def _reconciliation_csv(self):
        out = io.StringIO(newline='')
        w = csv.writer(out)
        w.writerow(['source_sheet', 'source_row', 'legacy_code', 'original_name', 'nickname',
                    'proposed_target_type', 'approved_target_type', 'verification_status',
                    'first_batch', 'last_batch', 'file_sha256'])
        codes = self.env['ei.legacy.code'].search(
            [('company_id', '=', self.company_id.id)], order='source_sheet_key, source_row')
        for c in codes:
            w.writerow([parsing.sanitize_cell(v) for v in (
                c.source_sheet, c.source_row, c.legacy_code, c.original_name, c.nickname or '',
                c.proposed_target_type, c.approved_target_type or '', c.verification_status,
                c.batch_id.name, c.last_batch_id.name, c.batch_id.file_sha256)])
        return out.getvalue().encode('utf-8-sig')

    def action_download_reconciliation(self):
        self.ensure_one()
        att = self.env['ir.attachment'].create({
            'name': 'EXI_reconciliation_%s.csv' % self.name.replace('/', '_'),
            'raw': self._reconciliation_csv(), 'mimetype': 'text/csv',
            'res_model': self._name, 'res_id': self.id,
        })
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%d?download=true' % att.id, 'target': 'self'}


class EiImportBatchSheet(models.Model):
    _name = 'ei.import.batch.sheet'
    _description = 'Import audit line per source sheet'
    _order = 'id'

    batch_id = fields.Many2one('ei.import.batch', required=True, ondelete='cascade', index=True)
    sheet_key = fields.Char('Source sheet', readonly=True)
    expected = fields.Integer(readonly=True)
    actual = fields.Integer(readonly=True)
    counts_ok = fields.Boolean(compute='_compute_counts_ok', store=True)
    created = fields.Integer(readonly=True)
    unchanged = fields.Integer(readonly=True)
    changed = fields.Integer(readonly=True)
    duplicates = fields.Integer(readonly=True)
    missing_nick = fields.Integer('Missing nickname', readonly=True)

    @api.depends('expected', 'actual')
    def _compute_counts_ok(self):
        for s in self:
            s.counts_ok = s.expected == s.actual


class EiImportDiff(models.Model):
    _name = 'ei.import.diff'
    _description = 'Difference between re-imported source and master'
    _order = 'id'

    batch_id = fields.Many2one('ei.import.batch', required=True, ondelete='cascade', index=True)
    code_id = fields.Many2one('ei.legacy.code', required=True, ondelete='cascade')
    field_label = fields.Char(readonly=True)
    old_value = fields.Char(readonly=True)
    new_value = fields.Char(readonly=True)
