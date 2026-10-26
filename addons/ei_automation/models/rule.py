"""Rules & Controls: the business-owned switchboard for the automation recipes, with a full log.

Safety design, all enforced here and tested:
  * every rule ships OFF; only the management role can switch one on or change its numbers, and each change is logged;
  * PREVIEW shows exactly what a run would do and creates nothing;
  * the only side effect of a live run is an internal reminder (an Odoo activity) for a colleague who can open the record;
  * a reminder is never created twice while the first is still open, nor again inside the repeat window;
  * a cap limits how many reminders one run may create; a failing recipe never stops the others;
  * every run and every finding is kept (who, when, found, created, skipped and why).
"""
from datetime import timedelta
from markupsafe import Markup, escape

from odoo import api, fields, models, tools, _
from odoo.exceptions import AccessError, UserError

from .recipes import RECIPES, MANAGEMENT_GROUP

AUTO_PREFIX = 'Auto reminder'


class EiRule(models.Model):
    _name = 'ei.rule'
    _description = 'Automation rule (business-owned switch)'
    _inherit = ['mail.thread']
    _order = 'code, id'

    key = fields.Selection([(k, str(v['name'])) for k, v in RECIPES.items()], required=True, readonly=True)
    name = fields.Char(compute='_compute_info')
    code = fields.Char('Brief reference', compute='_compute_info', store=True, help="The A-number of this automation in the project brief.")
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    enabled = fields.Boolean('Switched on', default=False, tracking=True,
                             help="Off by default. While it is off the schedule ignores it; you can still preview what it would do.")
    days = fields.Integer('Days', default=1, tracking=True)
    days_label = fields.Char(compute='_compute_info')
    repeat_days = fields.Integer('Remind again after (days)', default=3, tracking=True,
                                 help="If the reminder was closed but the problem is still there, remind again after this many days.")
    max_per_run = fields.Integer('At most this many reminders per run', default=20, tracking=True)
    explanation = fields.Html(compute='_compute_info', sanitize=False)
    last_run_at = fields.Datetime(readonly=True)
    last_found = fields.Integer(readonly=True)
    last_created = fields.Integer(readonly=True)
    run_ids = fields.One2many('ei.rule.run', 'rule_id', readonly=True)

    _key_company = models.Constraint('unique(company_id, key)', 'This automation already exists for this company.')

    @api.depends('key')
    def _compute_info(self):
        for r in self:
            rec = RECIPES.get(r.key)
            if not rec:
                r.name = r.code = r.days_label = r.explanation = False
                continue
            r.name, r.code, r.days_label = str(rec['name']), rec['code'], str(rec['days_label'])
            r.explanation = Markup(
                '<p><b>%s</b> %s</p><p><b>%s</b> %s</p><p><b>%s</b> %s</p><p><b>%s</b> %s</p>'
                '<p><b>%s</b> %s</p><p class="text-muted">%s</p>') % (
                _("What it looks at:"), str(rec['checks']), _("What it does:"), str(rec['does']),
                _("Who is told:"), str(rec['owner_text']),
                _("What it never does:"), _("It does not post, pay, send anything outside the company, or change any record. It only leaves an internal reminder."),
                _("Repeats:"), _("A reminder is never created twice while the first is open, nor again inside the repeat window."),
                _("The numbers are proposals. The business decides them; every change is logged."))

    @api.constrains('days', 'repeat_days', 'max_per_run')
    def _check_numbers(self):
        for r in self:
            if r.days < 0 or r.repeat_days < 0 or r.max_per_run < 1 or r.max_per_run > 200:
                raise UserError(_("Days cannot be negative and a run may create between 1 and 200 reminders."))

    # ------------------------------------------------------------------ who may change a rule
    def _check_manager(self):
        if not self.env.su and not self.env.user.has_group(MANAGEMENT_GROUP):
            raise AccessError(_("Only the management role can run or change automation rules."))

    # ------------------------------------------------------------------ the engine
    def _run(self, mode):
        """mode: 'preview' (creates nothing), 'live' (a manager pressed Run), 'cron' (the schedule). Returns the run record."""
        self.ensure_one()
        sudo = self.sudo()
        run = self.env['ei.rule.run'].sudo().create({'rule_id': self.id, 'mode': mode, 'user_id': self.env.user.id})
        found = created = 0
        errors = ''
        try:
            findings = RECIPES[self.key]['find'](self.sudo().with_context(lang=self.env.user.lang).env, self.sudo())
            found = len(findings)
            for f in findings:
                rec = f.record
                status, note = self._decide(f, mode, created)
                row = {'run_id': run.id, 'res_model': rec._name, 'res_id': rec.id, 'record_name': rec.display_name, 'summary': f.summary,
                       'owners': ', '.join(f.owners.mapped('name')), 'status': status}
                if status == 'reminded':
                    for u in f.owners:
                        act = rec.sudo().activity_schedule('mail.mail_activity_data_todo', summary='%s: %s' % (AUTO_PREFIX, f.summary),
                                                           note=f.note, user_id=u.id)
                        row.setdefault('activity_ids', []).append(act.id)
                    created += 1
                row['activity_ids'] = [(6, 0, row.get('activity_ids', []))]
                self.env['ei.rule.finding'].sudo().create(row)
        except Exception as e:                                       # one failing recipe must not stop the others
            errors = '%s: %s' % (type(e).__name__, e)
        run.write({'found': found, 'created': created, 'errors': errors})
        if mode != 'preview':
            sudo.write({'last_run_at': fields.Datetime.now(), 'last_found': found, 'last_created': created})
        return run

    def _decide(self, f, mode, created_so_far):
        """Return (status, why). Duplicate protection and the per-run cap live here."""
        if not f.owners:
            return 'no_owner', _("Nobody who can open this record is available to tell.")
        rec = f.record
        # still open (any user): never pile up
        if self.env['mail.activity'].sudo().search_count([('res_model', '=', rec._name), ('res_id', '=', rec.id),
                                                          ('summary', '=', '%s: %s' % (AUTO_PREFIX, f.summary))]):
            return 'skipped_open', _("An earlier reminder is still open.")
        recent = self.env['ei.rule.finding'].sudo().search_count([
            ('run_id.rule_id', '=', self.id), ('res_model', '=', rec._name), ('res_id', '=', rec.id), ('status', '=', 'reminded'),
            ('create_date', '>=', fields.Datetime.now() - timedelta(days=self.repeat_days))])
        if recent:
            return 'skipped_recent', _("Reminded inside the last %s days.", self.repeat_days)
        if created_so_far >= self.max_per_run:
            return 'skipped_cap', _("This run already created %s reminders.", self.max_per_run)
        return ('would_remind' if mode == 'preview' else 'reminded'), ''

    # ------------------------------------------------------------------ buttons
    def action_preview(self):
        self.ensure_one()
        self._check_manager()
        return self._open_run(self._run('preview'))

    def action_run(self):
        self.ensure_one()
        self._check_manager()
        if not self.enabled:
            raise UserError(_("Switch this automation on first. Until then you can only preview it."))
        return self._open_run(self._run('live'))

    @staticmethod
    def _open_run(run):
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.rule.run', 'res_id': run.id, 'views': [(False, 'form')], 'target': 'current'}

    # ------------------------------------------------------------------ the schedule
    @api.model
    def cron_run_all(self):
        """Daily. Runs every switched-on rule; a failure in one is logged and the rest still run."""
        for rule in self.sudo().search([('enabled', '=', True)]):
            rule._run('cron')
            if not tools.config['test_enable']:        # one rule's work is saved before the next starts; tests cannot commit
                self.env.cr.commit()


class EiRuleRun(models.Model):
    _name = 'ei.rule.run'
    _description = 'One run of an automation rule (kept as an audit trail)'
    _order = 'id desc'

    rule_id = fields.Many2one('ei.rule', required=True, ondelete='cascade', index=True, readonly=True)
    company_id = fields.Many2one(related='rule_id.company_id', store=True, index=True)
    mode = fields.Selection([('preview', 'Preview (nothing created)'), ('live', 'Run by a manager'), ('cron', 'Run by the schedule')], readonly=True)
    run_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one('res.users', readonly=True)
    found = fields.Integer(readonly=True)
    created = fields.Integer('Reminders created', readonly=True)
    errors = fields.Text(readonly=True)
    finding_ids = fields.One2many('ei.rule.finding', 'run_id', readonly=True)

    @api.depends('rule_id', 'run_at')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s - %s' % (r.rule_id.name or '', fields.Datetime.to_string(r.run_at))


class EiRuleFinding(models.Model):
    _name = 'ei.rule.finding'
    _description = 'A record an automation rule looked at, and what it did about it'
    _order = 'id'

    run_id = fields.Many2one('ei.rule.run', required=True, ondelete='cascade', index=True, readonly=True)
    company_id = fields.Many2one(related='run_id.company_id', store=True, index=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    record_name = fields.Char('Record', readonly=True)
    summary = fields.Char(readonly=True)
    owners = fields.Char('Told', readonly=True)
    status = fields.Selection([
        ('would_remind', 'Would remind (preview)'), ('reminded', 'Reminded'), ('skipped_open', 'Skipped: reminder still open'),
        ('skipped_recent', 'Skipped: reminded recently'), ('skipped_cap', 'Skipped: limit reached'), ('no_owner', 'Nobody to tell'),
    ], readonly=True)
    activity_ids = fields.Many2many('mail.activity', readonly=True)

    def action_open_record(self):
        self.ensure_one()
        rec = self.env[self.res_model].browse(self.res_id).exists()
        rec.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': self.res_model, 'res_id': rec.id, 'views': [(False, 'form')], 'target': 'current'}
