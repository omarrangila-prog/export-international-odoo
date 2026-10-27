"""Scheduled delivery of a financial preview by email: strictly opt-in, to named colleagues only, every run logged.

* A schedule starts OFF. Only management can switch it on (and says so in the record's history); nothing is ever sent from a schedule that is off.
* Recipients are colleagues who have an internal login AND may see the report themselves. An outside address cannot be typed in.
* The PDF is worked out as the person who owns the schedule, so it can never show more than that person may see.
* Every run, on time or "send a test to me", writes a line: when, what, to whom, and what happened (sent, queued because no outgoing mail server is
  configured, failed, or skipped with the reason). Nothing is sent silently and nothing is hidden."""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

STATEMENTS = [('summary', "Summary of all four"), ('pnl', "Profit and loss"), ('balance_sheet', "Balance sheet"), ('trial_balance', "Trial balance"), ('cash_flow', "Cash flow")]
PERIODS = [('last_month', "The whole of last month"), ('month_to_date', "This month so far"), ('last_quarter', "The whole of last quarter"), ('year_to_date', "This year so far")]


class EiReportSchedule(models.Model):
    _name = 'ei.report.schedule'
    _description = "Scheduled delivery of a financial preview"
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, tracking=True)
    statement = fields.Selection(STATEMENTS, required=True, default='pnl', tracking=True)
    period_kind = fields.Selection(PERIODS, "Period", required=True, default='last_month', tracking=True)
    frequency = fields.Selection([('weekly', "Every Monday"), ('monthly', "On the 1st of each month")], required=True, default='monthly', tracking=True)
    recipient_ids = fields.Many2many('res.users', string="Send to", domain="[('share', '=', False)]", tracking=True,
                                     help="Colleagues with an internal login who may see this report. An outside address cannot be added.")
    owner_id = fields.Many2one('res.users', "Worked out as", required=True, default=lambda s: s.env.user, readonly=True,
                               help="The PDF shows only what this person may see.")
    enabled = fields.Boolean("Switched on", default=False, tracking=True, help="Off until management switches it on. Nothing is sent while it is off.")
    switched_on_by_id = fields.Many2one('res.users', readonly=True)
    next_run = fields.Date(readonly=True)
    last_run = fields.Datetime(readonly=True)
    run_ids = fields.One2many('ei.report.schedule.run', 'schedule_id', string="What was sent", readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)

    # ---------------------------------------------------------------- who
    def _is_manager(self):
        return self.env.user.has_group('ei_management_dashboard.group_ei_management')

    @api.constrains('recipient_ids')
    def _check_recipients(self):
        Fin = self.env['ei.report.financials']
        for s in self:
            for u in s.recipient_ids:
                if u.share:
                    raise UserError(_("%s is not a colleague with an internal login: a report is never sent outside.", u.name))
                if not Fin.with_user(u)._allowed():
                    raise UserError(_("%s may not see the financial previews, so cannot be sent one.", u.name))

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            v['enabled'] = False                   # a new schedule is always off, whatever the caller asked
        return super().create(vals_list)

    def write(self, vals):
        if 'enabled' in vals and not self.env.su:
            raise UserError(_("Use the Switch on / Switch off buttons."))
        if {'name', 'statement', 'period_kind', 'frequency', 'recipient_ids'} & set(vals) and not self.env.su and any(s.enabled for s in self):
            raise UserError(_("Switch it off before changing it, so that what was agreed is what runs."))
        return super().write(vals)

    # ---------------------------------------------------------------- dates
    def _period(self, on=None):
        on = on or fields.Date.context_today(self)
        first = on.replace(day=1)
        if self.period_kind == 'last_month':
            return first - relativedelta(months=1), first - relativedelta(days=1)
        if self.period_kind == 'month_to_date':
            return first, on
        if self.period_kind == 'last_quarter':
            q0 = on.replace(month=3 * ((on.month - 1) // 3) + 1, day=1)
            return q0 - relativedelta(months=3), q0 - relativedelta(days=1)
        return on.replace(month=1, day=1), on

    def _next_after(self, on):
        if self.frequency == 'weekly':
            return on + relativedelta(days=7 - on.weekday())                      # the next Monday
        return on.replace(day=1) + relativedelta(months=1)

    # ---------------------------------------------------------------- switching
    def action_switch_on(self):
        if not self._is_manager():
            raise AccessError(_("Only management can switch a scheduled delivery on."))
        for s in self:
            if not s.recipient_ids:
                raise UserError(_("Choose who it is sent to first."))
            s.sudo().write({'enabled': True, 'switched_on_by_id': self.env.user.id, 'next_run': s._next_after(fields.Date.context_today(s) - relativedelta(days=1))})
            s.message_post(body=_("Switched on by %(u)s. It will be sent to %(r)s.", u=self.env.user.name, r=", ".join(s.recipient_ids.mapped('name'))))
        return True

    def action_switch_off(self):
        if not self._is_manager() and self.env.user != self.owner_id:
            raise AccessError(_("Only management or the person it is worked out as can switch it off."))
        for s in self:
            s.sudo().write({'enabled': False, 'next_run': False})
            s.message_post(body=_("Switched off by %s.", self.env.user.name))
        return True

    # ---------------------------------------------------------------- sending
    def _render_pdf(self):
        self.ensure_one()
        d_from, d_to = self._period()
        pdf, _kind = self.env['ir.actions.report'].with_user(self.owner_id)._render_qweb_pdf(
            'ei_reports.report_financial', res_ids=None, data={'statement': self.statement, 'date_from': str(d_from), 'date_to': str(d_to)})
        return pdf, d_from, d_to

    def _deliver(self, users, test=False):
        """One delivery to these users. Returns the log line."""
        self.ensure_one()
        Run = self.env['ei.report.schedule.run'].sudo()
        label = dict(STATEMENTS)[self.statement]
        base = {'schedule_id': self.id, 'test': test, 'recipients': ", ".join(users.mapped('name'))}
        try:
            pdf, d_from, d_to = self._render_pdf()
        except Exception as e:                                               # a failed render is a result, not a crash
            return Run.create(dict(base, status='failed', message=_("The PDF could not be made: %s", str(e)[:300])))
        sendable = users.filtered(lambda u: u.email and not u.share and self.env['ei.report.financials'].with_user(u)._allowed())
        skipped = users - sendable
        if not sendable:
            return Run.create(dict(base, status='skipped', message=_("Nobody to send it to: %s have no email address or may not see the report.", ", ".join(skipped.mapped('name')) or _("(no one)"))))
        subject = _("Export International - %(s)s (PREVIEW) %(a)s to %(b)s", s=label, a=d_from, b=d_to)
        body = _("<p>Attached: <b>%(s)s</b>, %(a)s to %(b)s.</p><p><b>Preview.</b> Worked out from posted entries as they stand; the chart of accounts, opening balances and tax rules are "
                 "not approved by the accountant yet, so do not use it for tax, statutory accounts or a lender.</p><p>Sent by the scheduled delivery \"%(n)s\".</p>", s=label, a=d_from, b=d_to, n=self.name)
        att = self.env['ir.attachment'].sudo().create({'name': f"Export-International-{label.replace(' ', '-')}-{d_from}-{d_to}-PREVIEW.pdf", 'raw': pdf,
                                                       'mimetype': 'application/pdf', 'res_model': 'ei.report.schedule', 'res_id': self.id})
        mails = self.env['mail.mail'].sudo()
        for u in sendable:
            mails |= self.env['mail.mail'].sudo().create({'subject': subject, 'body_html': body, 'email_to': u.email, 'attachment_ids': [(6, 0, att.ids)],
                                                         'auto_delete': False, 'email_from': self.env.company.email or self.env.user.email_formatted})
        mails.send(raise_exception=False)
        states = set(mails.mapped('state'))
        status = 'sent' if states == {'sent'} else ('failed' if 'exception' in states else 'queued')
        msg = {'sent': _("Sent."), 'queued': _("Waiting in the outgoing mail queue (no outgoing mail server is configured, or it has not run yet)."),
               'failed': _("The mail server refused it: %s", "; ".join(filter(None, mails.mapped('failure_reason')))[:300])}[status]
        if skipped:
            msg += " " + _("Not sent to %s (no email address or may not see the report).", ", ".join(skipped.mapped('name')))
        return Run.create(dict(base, status=status, message=msg, attachment_id=att.id, period_text=f"{d_from} to {d_to}"))

    def action_send_test(self):
        """A test goes to the person who presses the button, and only to them."""
        for s in self:
            if not (self._is_manager() or self.env.user in (s.owner_id,)):
                raise AccessError(_("Only management or the owner can send a test."))
            s._deliver(self.env.user, test=True)
        return True

    @api.model
    def _cron_run_due(self):
        today = fields.Date.context_today(self)
        for s in self.sudo().search([('enabled', '=', True), ('next_run', '<=', today)]):
            try:
                s._deliver(s.recipient_ids)
            finally:
                s.write({'last_run': fields.Datetime.now(), 'next_run': s._next_after(today)})


class EiReportScheduleRun(models.Model):
    _name = 'ei.report.schedule.run'
    _description = "What a scheduled delivery did"
    _order = 'id desc'

    schedule_id = fields.Many2one('ei.report.schedule', required=True, ondelete='cascade', index=True)
    at = fields.Datetime("When", default=fields.Datetime.now, readonly=True)
    test = fields.Boolean("A test to the person who pressed the button", readonly=True)
    status = fields.Selection([('sent', "Sent"), ('queued', "Waiting in the mail queue"), ('failed', "Failed"), ('skipped', "Skipped")], required=True, readonly=True)
    period_text = fields.Char("Period", readonly=True)
    recipients = fields.Char("To", readonly=True)
    message = fields.Text("What happened", readonly=True)
    attachment_id = fields.Many2one('ir.attachment', "The PDF", readonly=True, ondelete='set null')
