"""Every way data comes into the system, in one list: bank statements, parent statements, the old code list, old-system extracts and
tax-authority submissions. One row per import or attempt, with its file fingerprint (the reason a repeat is refused), who, when and
where it stands. Read-only; it shows what happened and never claims a feed is live when it is not."""
from odoo import fields, models, tools


class EiIntegrationLog(models.Model):
    _name = 'ei.integration.log'
    _description = 'Imports and integrations log'
    _auto = False
    _order = 'happened_at desc'

    source = fields.Selection([('bank', 'Bank statement file'), ('parent', 'Parent statement file'), ('codes', 'Old code list'),
                               ('foxpro', 'Old system extract'), ('fbr', 'Tax authority (FBR) submission')], readonly=True)
    name = fields.Char('Reference', readonly=True)
    filename = fields.Char('File', readonly=True)
    fingerprint = fields.Char('Fingerprint (SHA-256 / key)', readonly=True)
    status = fields.Char(readonly=True)
    attempts = fields.Integer(readonly=True)
    error = fields.Char('Problem', readonly=True)
    user_id = fields.Many2one('res.users', 'By', readonly=True)
    happened_at = fields.Datetime('When', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW ei_integration_log AS (
                SELECT ROW_NUMBER() OVER () AS id, * FROM (
                    SELECT 'bank'::varchar AS source, b.name, b.filename, b.file_sha256 AS fingerprint, b.state::varchar AS status,
                           1 AS attempts, LEFT(b.issues, 200) AS error, b.imported_by AS user_id, b.create_date AS happened_at, b.company_id
                      FROM ei_bank_import b
                    UNION ALL
                    SELECT 'parent', p.name, p.filename, p.file_sha256, p.state, 1, LEFT(p.issues, 200), p.imported_by, p.create_date, p.company_id
                      FROM ei_parent_statement p
                    UNION ALL
                    SELECT 'codes', c.name, c.filename, c.file_sha256, c.state, 1, LEFT(c.error_log, 200), c.imported_by, c.imported_at, c.company_id
                      FROM ei_import_batch c
                    UNION ALL
                    SELECT 'foxpro', e.name, 'manifest.json', e.manifest_sha256, 'recorded', 1, LEFT(e.problems, 200), e.imported_by, e.imported_at, e.company_id
                      FROM ei_migration_extract e
                    UNION ALL
                    SELECT 'fbr', m.name, NULL, s.idempotency_key, s.state, s.attempts, s.last_error, s.create_uid, COALESCE(s.submitted_at, s.write_date), s.company_id
                      FROM ei_compliance_submission s JOIN account_move m ON m.id = s.move_id
                ) u
            )""")
