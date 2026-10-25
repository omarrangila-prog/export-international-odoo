from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class EiBankDailyClose(models.Model):
    _name = 'ei.bank.daily.close'
    _description = 'Daily bank posting review (4-5 p.m. close)'
    _order = 'date desc, journal_id'

    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', '=', 'bank')]", index=True)
    company_id = fields.Many2one(related='journal_id.company_id', store=True, index=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    state = fields.Selection([('open', 'Open'), ('closed', 'Closed')], default='open', readonly=True)
    closed_by = fields.Many2one('res.users', readonly=True)
    closed_at = fields.Datetime(readonly=True)
    n_imported = fields.Integer('Imported', compute='_compute_counts')
    n_processed = fields.Integer('Processed (posted)', compute='_compute_counts')
    n_unmatched = fields.Integer('Unmatched', compute='_compute_counts')
    n_duplicate = fields.Integer('Duplicate', compute='_compute_counts')
    n_rejected = fields.Integer('Rejected', compute='_compute_counts')
    n_reviewed = fields.Integer('Reviewed', compute='_compute_counts')
    snapshot = fields.Char('Counts at close', readonly=True)

    _uniq = models.Constraint('unique(journal_id, date)', 'This journal already has a daily close for that date.')

    def _lines(self):
        self.ensure_one()
        return self.env['ei.bank.import.line'].search([
            ('journal_id', '=', self.journal_id.id), ('imported_on', '=', self.date)])

    @api.depends('journal_id', 'date')
    def _compute_counts(self):
        for r in self:
            st = {}
            for line in r._lines() if r.id or r.journal_id else []:
                st[line.state] = st.get(line.state, 0) + 1
            r.n_imported = sum(st.values())
            r.n_processed = st.get('posted', 0)
            r.n_unmatched = st.get('new', 0) + st.get('proposed', 0) + st.get('unidentified', 0)
            r.n_duplicate = st.get('duplicate', 0)
            r.n_rejected = st.get('rejected', 0)
            r.n_reviewed = st.get('verified', 0) + st.get('posted', 0)

    def action_close(self):
        for r in self:
            if not self.env.user.has_group('ei_bank_operations.group_ei_bank_approver'):
                raise AccessError(_("Only a bank approver can close the day."))
            if r.state == 'closed':
                continue
            pending = r._lines().filtered(lambda l: l.state in ('new', 'proposed', 'verified', 'unidentified'))
            if pending:
                raise UserError(_("%s imported lines are not posted yet (unresolved, or approved but unposted); "
                                  "post or resolve them before closing.", len(pending)))
            r.write({'state': 'closed', 'closed_by': self.env.user.id, 'closed_at': fields.Datetime.now(),
                     'snapshot': 'imported %s / posted %s / unidentified-in-suspense %s / duplicate %s / rejected %s' % (
                         r.n_imported, r.n_processed,
                         len(r._lines().filtered(lambda l: l.is_unidentified and l.state == 'posted')),
                         r.n_duplicate, r.n_rejected)})
