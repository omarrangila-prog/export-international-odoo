"""My Work Today: the real records that wait for a person, with assign / snooze / escalate.

Nothing is invented. A task IS a record in a waiting state (a contract waiting for approval, a truck loading
waiting to be verified ...). "Completing" a task means doing the real step on that record; the task then disappears
by itself. What this adds on top of the records:
  * priority and waiting time, worked out from the record's own dates (rules shown to the user),
  * assignment, using Odoo's own activities (so it also appears in the standard Activities menu and notifies),
  * snooze, private to one user (a row in ei.work.snooze),
  * escalation to the management role (an activity for each manager plus a note on the record).
Every call runs as the current user, so access rules decide what can be seen and changed.
"""
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import format_amount

PER_TYPE = 12                 # newest-waiting-longest first, per task type
MAX_ITEMS = 60
OVERDUE_PARAM = 'ei_ui_theme.approval_overdue_days'
OVERDUE_DEFAULT = 2.0         # PROPOSED default: the client has not set an approval deadline yet
HIGH_DAYS = 3
ESCALATED_PREFIX = 'Escalated: '
SNOOZE_CHOICES = {1: _("until tomorrow"), 3: _("for 3 days"), 7: _("for a week")}

# key, model, domain, title of the step, next action label, groups that may do the step, maker field, party field,
# amount field, "problem" flag (these are shown as high priority at once)
WORK = [
    dict(key='contract_approve', verb=_("Approve"), model='ei.contract', domain=[('state', '=', 'reviewed')], step=_("Approve contract"),
         next=_("Check the papers, then approve"), groups=('ei_contract_da.group_ei_contract_approver',),
         maker='maker_id', party='parent_partner_id'),
    dict(key='da_approve', verb=_("Approve"), model='ei.da', domain=[('state', '=', 'under_review')], step=_("Approve delivery advice"),
         next=_("Check quantities and rates, then approve"), groups=('ei_contract_da.group_ei_contract_approver',),
         maker='maker_id', party='parent_partner_id'),
    dict(key='order_approve', verb=_("Approve"), model='ei.daily.order', domain=[('state', '=', 'draft')], step=_("Approve daily order"),
         next=_("Approve, then print or email"), groups=('ei_daily_orders.group_ei_order_approver',),
         maker='maker_id', party='parent_partner_id'),
    dict(key='lifting_verify', verb=_("Verify"), model='ei.lifting', domain=[('state', '=', 'draft')], step=_("Verify truck loading"),
         next=_("Check the gate pass and weighbridge slip"), groups=('ei_material_lifting.group_ei_lifting_reviewer',),
         maker='maker_id', party='customer_id'),
    dict(key='voucher_approve', verb=_("Approve"), model='ei.cash.voucher', domain=[('state', '=', 'submitted')], step=_("Approve cash voucher"),
         next=_("Check the receipt, then approve"), groups=('ei_cashbook.group_ei_cash_approver',),
         maker='maker_id', party='partner_id', amount='amount'),
    dict(key='bank_approve', verb=_("Approve"), model='ei.bank.import', domain=[('state', 'in', ('received', 'validated', 'proposed'))],
         step=_("Approve bank statement"), next=_("Check the payments, then approve"),
         groups=('ei_bank_operations.group_ei_bank_approver',), maker='imported_by'),
    dict(key='bank_post', verb=_("Post"), model='ei.bank.import', domain=[('state', '=', 'approved')], step=_("Post bank statement"),
         next=_("Post it into the books"), groups=('ei_bank_operations.group_ei_bank_poster',), maker='approved_by'),
    dict(key='bank_check', verb=_("Match"), model='ei.bank.import.line', domain=[('state', 'in', ('new', 'proposed', 'unidentified'))],
         step=_("Match bank payment"), next=_("Confirm who paid"),
         groups=('ei_bank_operations.group_ei_bank_officer',), party='suggested_partner_id', amount='amount'),
    dict(key='intake_problem', verb=_("Fix"), model='ei.supplier.intake', domain=[('state', '=', 'mismatch')], step=_("Fix supplier invoice"),
         next=_("See what does not match"), groups=('ei_invoice_extensions.group_ei_invoicing',), party='partner_id',
         amount='stated_total', problem=True),
    dict(key='to_invoice', verb=_("Invoice"), model='ei.lifting', domain=[('invoice_status', '=', 'to_invoice')], step=_("Invoice delivered material"),
         next=_("Create the customer invoice"), groups=('ei_invoice_extensions.group_ei_invoicing',), party='customer_id'),
    dict(key='recon_diff', verb=_("Resolve"), model='ei.parent.statement.line', domain=[('status', '!=', 'matched'), ('resolution_state', '=', 'open')],
         step=_("Resolve difference with parent company"), next=_("Find the reason and record it"),
         groups=('ei_parent_reconciliation.group_ei_recon_user',), amount='difference'),
    dict(key='recon_signoff', verb=_("Sign off"), model='ei.parent.statement', domain=[('state', '=', 'resolved')], step=_("Sign off parent statement"),
         next=_("Check and sign off"), groups=('ei_parent_reconciliation.group_ei_recon_approver',), party='partner_id'),
    dict(key='code_classify', verb=_("Classify"), model='ei.legacy.code', domain=[('verification_status', 'in', ('proposed', 'needs_review'))],
         step=_("Classify old code"), next=_("Decide what this old code becomes"),
         groups=('ei_legacy_master.group_ei_mapping_approver',), bulk=True),
    dict(key='formula_approve', verb=_("Approve"), model='ei.formula.definition', domain=[('state', '=', 'draft')], step=_("Approve formula"),
         next=_("Test it, then approve"), groups=('ei_contract_da.group_ei_formula_approver',)),
]
WORK_BY_KEY = {w['key']: w for w in WORK}
WORK_MODELS = {w['model'] for w in WORK}


class EiWorkSnooze(models.Model):
    _name = 'ei.work.snooze'
    _description = 'A task one user has put aside for a few days'

    user_id = fields.Many2one('res.users', required=True, index=True, default=lambda s: s.env.user, ondelete='cascade')
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    until = fields.Date(required=True, help="The task comes back on this day.")

    _one_per_task = models.Constraint('unique(user_id, res_model, res_id)', 'This task is already snoozed.')


class EiWork(models.AbstractModel):
    _name = 'ei.work'
    _description = 'My Work Today'

    # ------------------------------------------------------------------ helpers
    def _overdue_days(self):
        return self.env['ir.config_parameter'].sudo().get_float(OVERDUE_PARAM, OVERDUE_DEFAULT)

    def _can_act(self, spec):
        return any(self.env.user.has_group(g) for g in spec['groups'])

    def _record(self, model, res_id):
        """The record a task button refers to, only for known task models and only if readable."""
        if model not in WORK_MODELS:
            raise AccessError(_("This kind of record is not part of My Work."))
        rec = self.env[model].browse(int(res_id)).exists()
        if not rec:
            raise UserError(_("This record no longer exists."))
        rec.check_access('read')
        return rec

    @staticmethod
    def _age_text(days):
        if days <= 0:
            return _("New today")
        return _("Waiting 1 day") if days == 1 else _("Waiting %s days", days)

    def _priority(self, spec, days):
        if spec.get('problem') or days >= HIGH_DAYS:
            return 'high'
        return 'medium' if days >= 1 else 'low'

    # ------------------------------------------------------------------ the list
    @api.model
    def tasks(self, show_snoozed=False):
        env, me, today = self.env, self.env.user, fields.Date.context_today(self)
        if not env['ei.work.snooze'].has_access('read'):        # a user with no Export International role has no work
            return {'items': [], 'total': 0, 'oversight': False, 'rules': '',
                    'counts': {'open': 0, 'snoozed': 0, 'mine': 0, 'escalated': 0, 'overdue': 0, 'others': 0}}
        now = fields.Datetime.now()
        overdue = self._overdue_days()
        snoozed = {(s.res_model, s.res_id): s.until for s in env['ei.work.snooze'].search(
            [('user_id', '=', me.id), ('until', '>', today)])}
        items, counts = [], {'open': 0, 'snoozed': 0, 'mine': 0, 'escalated': 0, 'overdue': 0, 'others': 0}
        oversight = me.has_group('ei_legacy_master.group_ei_auditor')   # management / auditor: see what is stuck
        for spec in WORK:
            model = spec['model']
            if model not in env or not env[model].has_access('read'):
                continue
            can_act = self._can_act(spec)
            if not can_act and not oversight:
                continue
            recs = env[model].search(spec['domain'], order='write_date asc, id asc', limit=PER_TYPE * 3)
            if not recs:
                continue
            if spec.get('bulk'):
                if not can_act:
                    continue
                n = env[model].search_count(spec['domain'])
                oldest = recs[0].write_date or now
                days = max((now - oldest).days, 0)
                items.append({
                    'id': '%s:bulk' % model, 'model': model, 'res_id': 0, 'type': spec['key'], 'bulk': True, 'step': spec['step'],
                    'title': _("%s old codes are waiting for a decision", n), 'party': '', 'party_id': False, 'amount': '',
                    'priority': 'low', 'age_days': days, 'age_text': self._age_text(days), 'overdue': False, 'status': 'open',
                    'assignee': '', 'assignee_me': False, 'due': '', 'my_activity': False, 'escalated_by': '', 'snoozed_until': '',
                    'next': spec['next'], 'can_act': can_act, 'view_only': not can_act, 'can_assign': False, 'can_escalate': False})
                counts['open'] += 1
                continue
            acts = {}
            for a in env['mail.activity'].sudo().search([('res_model', '=', model), ('res_id', 'in', recs.ids)], order='date_deadline'):
                acts.setdefault(a.res_id, []).append(a)
            for rec in recs:
                maker = rec[spec['maker']] if spec.get('maker') else env['res.users']
                days = max((now - (rec.write_date or now)).days, 0)
                rec_acts = acts.get(rec.id, [])
                escalated = [a for a in rec_acts if (a.summary or '').startswith(ESCALATED_PREFIX)]
                assigned = [a for a in rec_acts if a not in escalated]
                mine_act = next((a for a in rec_acts if a.user_id == me), None)
                if not can_act and days < overdue and not spec.get('problem') and not mine_act:
                    continue                      # oversight roles see what is stuck or a problem, or what was handed to them
                if can_act and maker and maker == me and not mine_act:
                    counts['others'] += 1                      # maker-checker: someone else must do this step
                    continue
                key = (model, rec.id)
                if key in snoozed and not show_snoozed:
                    counts['snoozed'] += 1
                    continue
                if show_snoozed and key not in snoozed:
                    continue
                party = rec[spec['party']] if spec.get('party') else env['res.partner']
                amount = ''
                if spec.get('amount') and rec[spec['amount']]:
                    cur = rec['currency_id'] if 'currency_id' in rec._fields and rec['currency_id'] else env.company.currency_id
                    amount = format_amount(env, abs(rec[spec['amount']]), cur)
                who = (assigned[0].user_id if assigned else env['res.users'])
                status = 'snoozed' if key in snoozed else 'escalated' if escalated else 'assigned' if assigned else 'open'
                is_overdue = days >= overdue and not spec.get('problem')
                items.append({
                    'id': '%s:%s' % (model, rec.id), 'model': model, 'res_id': rec.id, 'type': spec['key'],
                    'step': spec['step'], 'verb': spec['verb'], 'title': rec.display_name, 'party': party.name or '', 'party_id': party.id or False,
                    'amount': amount, 'priority': self._priority(spec, days), 'age_days': days, 'age_text': self._age_text(days),
                    'overdue': is_overdue, 'status': status,
                    'assignee': who.name or '', 'assignee_me': bool(who) and who == me,
                    'due': fields.Date.to_string(assigned[0].date_deadline) if assigned and assigned[0].date_deadline else '',
                    'my_activity': mine_act.id if mine_act else False,
                    'escalated_by': escalated[0].create_uid.name if escalated else '',
                    'snoozed_until': fields.Date.to_string(snoozed[key]) if key in snoozed else '',
                    'next': spec['next'], 'can_act': can_act, 'view_only': not can_act,
                    'can_assign': can_act and 'activity_ids' in rec._fields and rec.has_access('write'),
                    'can_escalate': 'activity_ids' in rec._fields and rec.has_access('write') and not escalated,
                })
                counts['open'] += 0 if show_snoozed else 1
                counts['mine'] += 1 if (who and who == me) else 0
                counts['escalated'] += 1 if escalated else 0
                counts['overdue'] += 1 if is_overdue else 0
        order = {'high': 0, 'medium': 1, 'low': 2}
        items.sort(key=lambda t: (t['view_only'], t['status'] != 'escalated', order[t['priority']], -t['age_days']))
        return {'items': items[:MAX_ITEMS], 'total': len(items), 'counts': counts, 'oversight': oversight and not any(
            self._can_act(s) for s in WORK),
            'rules': _("Priority: high = a problem or waiting %(h)s days or more; medium = waiting a day or more. "
                       "Overdue = waiting %(o)s days or more (change it in Settings).", h=HIGH_DAYS, o=int(overdue))}

    # ------------------------------------------------------------------ buttons
    @api.model
    def open_task(self, model, res_id):
        if int(res_id) == 0:                      # a bulk line (many records): open the list, not one record
            spec = next((w for w in WORK if w['model'] == model and w.get('bulk')), None)
            if not spec:
                raise UserError(_("This record no longer exists."))
            self.env[model].check_access('read')
            return {'type': 'ir.actions.act_window', 'name': spec['step'], 'res_model': model, 'domain': spec['domain'],
                    'views': [(False, 'list'), (False, 'form')], 'target': 'current'}
        rec = self._record(model, res_id)
        return {'type': 'ir.actions.act_window', 'res_model': model, 'res_id': rec.id, 'views': [(False, 'form')], 'target': 'current'}

    @api.model
    def snooze(self, model, res_id, days):
        rec = self._record(model, res_id)
        days = int(days)
        if days not in SNOOZE_CHOICES:
            raise UserError(_("Choose tomorrow, 3 days or a week."))
        until = fields.Date.context_today(self) + timedelta(days=days)
        row = self.env['ei.work.snooze'].search([('user_id', '=', self.env.user.id), ('res_model', '=', model), ('res_id', '=', rec.id)])
        row.write({'until': until}) if row else self.env['ei.work.snooze'].create({'res_model': model, 'res_id': rec.id, 'until': until})
        return {'until': fields.Date.to_string(until)}

    @api.model
    def unsnooze(self, model, res_id):
        self._record(model, res_id)
        self.env['ei.work.snooze'].search([('user_id', '=', self.env.user.id), ('res_model', '=', model), ('res_id', '=', int(res_id))]).unlink()
        return True

    @api.model
    def assignable_users(self, model, res_id):
        """People who may do this step (so a task is never given to someone who cannot complete it)."""
        rec = self._record(model, res_id)
        spec = next((w for w in WORK if w['model'] == model and rec.filtered_domain(w['domain'])), None)
        if not spec:
            raise UserError(_("This task is already done, so there is nothing left to assign."))
        users = self.env['res.users'].search([('share', '=', False), ('company_ids', 'in', rec.company_id.ids if 'company_id' in rec._fields and rec.company_id else self.env.companies.ids)])
        ok = users.filtered(lambda u: any(u.has_group(g) for g in spec['groups']) and u != self.env.user)
        return [{'id': u.id, 'name': u.name} for u in ok.sorted('name')[:30]]

    @api.model
    def assign(self, model, res_id, user_id, deadline=None, note=None):
        rec = self._record(model, res_id)
        if 'activity_ids' not in rec._fields:
            raise UserError(_("This kind of record cannot be assigned yet."))
        if not any(u['id'] == int(user_id) for u in self.assignable_users(model, res_id)):
            raise UserError(_("That person is not allowed to do this step."))
        try:
            act = rec.activity_schedule('mail.mail_activity_data_todo', date_deadline=deadline or False,
                                        summary=_("Please handle: %s", self._step_of(rec)), note=note or False, user_id=int(user_id))
        except AccessError:
            raise AccessError(_("You can assign work only on records you are allowed to change."))
        return {'activity_id': act.id}

    def _step_of(self, rec):
        spec = next((w for w in WORK if w['model'] == rec._name and rec.filtered_domain(w['domain'])), None)
        return spec['step'] if spec else rec.display_name

    @api.model
    def escalate(self, model, res_id, note):
        """Tell every manager. A reason is required so the manager knows why it cannot wait."""
        rec = self._record(model, res_id)
        note = (note or '').strip()
        if len(note) < 5:
            raise UserError(_("Please write why this cannot wait."))
        managers = self.env.ref('ei_management_dashboard.group_ei_management').sudo().user_ids.filtered(
            lambda u: u.active and not u.share and u != self.env.user)
        if not managers:
            raise UserError(_("No manager is set up to receive escalations. Ask the administrator to give someone the management role."))
        try:
            for m in managers:
                rec.activity_schedule('mail.mail_activity_data_todo', summary=ESCALATED_PREFIX + self._step_of(rec),
                                      note=_("Escalated by %(who)s: %(why)s", who=self.env.user.name, why=note), user_id=m.id)
            rec.message_post(body=_("Escalated to management by %(who)s: %(why)s", who=self.env.user.name, why=note))
        except AccessError:
            raise AccessError(_("You can escalate only records you are allowed to change."))
        return {'managers': managers.mapped('name')}

    @api.model
    def done(self, activity_id):
        """Close MY reminder. The underlying record stays until its real step is done."""
        act = self.env['mail.activity'].browse(int(activity_id)).exists()
        if not act or act.user_id != self.env.user or act.res_model not in WORK_MODELS:
            raise AccessError(_("You can only close your own reminders."))
        act.action_feedback(feedback=_("Closed from My Work"))
        return True
