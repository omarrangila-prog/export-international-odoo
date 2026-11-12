"""Maker-checker, the way the client works: one person enters and submits; a different authorised person approves, returns it for
correction, or rejects it. One request per submission (a resubmission is a new round of the same document).

    DRAFT -> (Submit for approval) -> PENDING APPROVAL -> APPROVED -> the document's next stage (FINALIZED)
                                      PENDING APPROVAL -> RETURNED FOR CORRECTION -> (corrected, resubmitted) -> PENDING ...
                                      PENDING APPROVAL -> REJECTED

What is enforced here, on the server, whatever the screen shows:
  * the checker is never the maker (also when the checker holds every role, and with no "small amount" exception);
  * the checker holds the role the document itself demands, and the rule's role / named checkers when a rule sets them;
  * the request is still pending (locked row: two checkers cannot both decide it) and the document is still what was submitted
    (a fingerprint of its figures; a document changed after submission cannot be approved, it must be resubmitted);
  * a reason is required to return or reject;
  * the document's own approval method still runs and still checks everything it checked before (rates, quantities, codes, the
    exchange rate, posting rights). An approval never posts what that method would refuse.
The request and its timeline are written by the engine (sudo) only after these checks; the document itself always changes as the
person who decided."""
import hashlib
import json
from datetime import timedelta

from psycopg2 import errors as pg_errors

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_amount, format_datetime

from .rule import FLOW_SELECTION

STATES = [('pending', "Pending approval"), ('approved', "Approved"), ('returned', "Returned for correction"),
          ('rejected', "Rejected"), ('withdrawn', "Withdrawn by the maker"), ('superseded', "Changed after submission")]
EVENTS = [('submitted', "Submitted"), ('resubmitted', "Resubmitted"), ('assigned', "Assigned"), ('unassigned', "Assignment required"),
          ('approved', "Approved"), ('finalized', "Moved to its next stage"), ('returned', "Returned for correction"),
          ('rejected', "Rejected"), ('withdrawn', "Withdrawn"), ('superseded', "Changed after submission"), ('escalated', "Overdue: escalated"),
          ('reassigned', "Reassigned"), ('comment', "Comment"), ('refused', "Approval refused")]
NOTICES = [('request', "New request for you"), ('approved', "Your entry was approved"), ('returned', "Your entry was returned"),
           ('rejected', "Your entry was rejected"), ('assignment', "No checker could be assigned"), ('escalated', "Overdue request"),
           ('superseded', "A request changed after submission")]


class EiApprovalRequest(models.Model):
    _name = 'ei.approval.request'
    _description = 'Approval request'
    _order = 'submitted_at desc, id desc'
    _rec_name = 'name'

    name = fields.Char(required=True, readonly=True)
    flow = fields.Selection(FLOW_SELECTION, string='Document type', required=True, readonly=True, index=True)
    res_model = fields.Char(required=True, readonly=True, index=True)
    res_id = fields.Integer(required=True, readonly=True, index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Customer / party', readonly=True)
    amount = fields.Monetary(readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', readonly=True)
    maker_id = fields.Many2one('res.users', string='Submitted by', required=True, readonly=True, index=True)
    approver_id = fields.Many2one('res.users', string='Assigned checker', readonly=True, index=True)
    eligible_user_ids = fields.Many2many('res.users', 'ei_approval_request_eligible_rel', 'request_id', 'user_id',
                                         string='Who may check', readonly=True)
    needs_assignment = fields.Boolean('Assignment required', readonly=True, index=True)
    rule_id = fields.Many2one('ei.approval.rule', readonly=True)
    state = fields.Selection(STATES, required=True, default='pending', readonly=True, index=True)
    urgent = fields.Boolean(readonly=True, help="Marked urgent by the maker, or overdue.")
    round = fields.Integer(default=1, readonly=True, help="1 = first submission; 2 = first resubmission ...")
    submitted_at = fields.Datetime(required=True, readonly=True, index=True)
    due_at = fields.Datetime(readonly=True)
    escalated_at = fields.Datetime(readonly=True)
    decided_at = fields.Datetime(readonly=True)
    decided_by = fields.Many2one('res.users', readonly=True)
    decision_note = fields.Text(readonly=True)
    submit_note = fields.Text(readonly=True)
    fingerprint = fields.Char(readonly=True)
    facts = fields.Json(readonly=True)
    event_ids = fields.One2many('ei.approval.event', 'request_id', readonly=True)
    is_overdue = fields.Boolean(compute='_compute_overdue', search='_search_overdue')
    priority = fields.Selection([('normal', "Normal"), ('urgent', "Urgent")], compute='_compute_overdue')
    wait_hours = fields.Float(compute='_compute_overdue')

    @api.depends('state', 'due_at', 'urgent')
    def _compute_overdue(self):
        now = fields.Datetime.now()
        for r in self:
            r.is_overdue = r.state == 'pending' and bool(r.due_at) and r.due_at < now
            r.priority = 'urgent' if (r.urgent or r.is_overdue or (r.state == 'pending' and r.needs_assignment)) else 'normal'
            end = r.decided_at or now
            r.wait_hours = round(((end - r.submitted_at).total_seconds() / 3600.0), 1) if r.submitted_at else 0.0

    def _search_overdue(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_("Unsupported search."))
        overdue = [('state', '=', 'pending'), ('due_at', '<', fields.Datetime.now())]
        return overdue if (operator == '=') == value else ['!', '&'] + overdue

    # ------------------------------------------------------------------ the document behind a request
    def _record(self):
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id).exists()

    @api.model
    def _pending_for(self, rec):
        return self.sudo().search([('res_model', '=', rec._name), ('res_id', '=', rec.id), ('state', '=', 'pending')], limit=1)

    @api.model
    def _latest_for(self, rec):
        return self.sudo().search([('res_model', '=', rec._name), ('res_id', '=', rec.id)], order='round desc, id desc', limit=1)

    @api.model
    def _fingerprint(self, rec):
        data = rec._ei_ap_fingerprint_values()
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    # ------------------------------------------------------------------ who may check
    @api.model
    def _eligible(self, rec, rule, maker):
        """Users who may check this document: the document's own role, the rule's role or named list, same company, active, not the maker."""
        Users = self.env['res.users'].sudo()
        need = self.env.ref(rec._ei_ap_group)
        dom = [('share', '=', False), ('active', '=', True), ('all_group_ids', 'in', [need.id]), ('company_ids', 'in', [rec._ei_ap_company().id])]
        if rule and rule.approver_group_id:
            dom.append(('all_group_ids', 'in', [rule.approver_group_id.id]))
        users = Users.search(dom)
        if rule and rule.approver_user_ids:
            users = rule.approver_user_ids.filtered(lambda u: u in users)
        return users.filtered(lambda u: u != maker and u.id != 1)              # never the maker; never the internal superuser

    @api.model
    def _pick(self, users):
        """The least busy eligible checker (named checkers keep their order when equally busy)."""
        if not users:
            return users
        load = {u.id: 0 for u in users}
        for row in self.sudo()._read_group([('state', '=', 'pending'), ('approver_id', 'in', users.ids)], ['approver_id'], ['__count']):
            load[row[0].id] = row[1]
        order = {u.id: i for i, u in enumerate(users)}
        admin = self.env.ref('base.group_system')
        # a business checker first; a system administrator only when nobody else holds the role
        return users.sorted(lambda u: (admin in u.all_group_ids, load[u.id], order[u.id]))[:1]

    # ------------------------------------------------------------------ submit
    @api.model
    def _submit(self, rec, note=None, urgent=False):
        """Called right after the document's own 'submit' step. Idempotent: an existing pending request is returned unchanged."""
        rec.ensure_one()
        existing = self._pending_for(rec)
        if existing:
            return existing
        maker = rec._ei_ap_maker() or self.env.user
        info = rec._ei_ap_info()
        rule = self.env['ei.approval.rule']._for(rec._ei_ap_flow, rec._ei_ap_company(), info.get('amount') or 0.0, maker)
        eligible = self._eligible(rec, rule, maker)
        approver = self._pick(eligible)
        prev = self._latest_for(rec)
        rnd = (prev.round + 1) if prev else 1
        now = fields.Datetime.now()
        due_hours = rule.due_hours if rule else int(self.env['ir.config_parameter'].sudo().get_float('ei_ui_theme.approval_overdue_days', 2.0) * 24)
        req = self.sudo().create({
            'name': info['name'], 'flow': rec._ei_ap_flow, 'res_model': rec._name, 'res_id': rec.id, 'company_id': rec._ei_ap_company().id,
            'partner_id': info.get('partner') and info['partner'].id, 'amount': info.get('amount') or 0.0,
            'currency_id': info.get('currency') and info['currency'].id, 'maker_id': maker.id, 'approver_id': approver.id or False,
            'eligible_user_ids': [(6, 0, eligible.ids)], 'needs_assignment': not approver, 'rule_id': rule.id or False,
            'round': rnd, 'submitted_at': now, 'due_at': now + timedelta(hours=due_hours), 'urgent': bool(urgent),
            'submit_note': (note or '').strip() or False, 'fingerprint': self._fingerprint(rec), 'facts': rec._ei_ap_facts(),
        })
        req._event('resubmitted' if rnd > 1 else 'submitted', note=note, user=maker)
        if approver:
            req._event('assigned', note=_("Assigned to %s.", approver.name), user=self.env.ref('base.user_root'))
            req._notify(approver, 'request')
            rec._ei_ap_post(_("Submitted for approval by %(m)s; assigned to %(a)s.", m=maker.name, a=approver.name))
        else:
            req._event('unassigned', note=_("No eligible checker other than the maker. An administrator must assign one."), user=self.env.ref('base.user_root'))
            admins = self.env['res.users'].sudo().search([('share', '=', False), ('active', '=', True),
                                                          ('all_group_ids', 'in', [self.env.ref('base.group_system').id])]).filtered(lambda u: u.id != 1)
            for a in admins:
                req._notify(a, 'assignment')
            rec._ei_ap_post(_("Submitted for approval by %s. Assignment required: no other person holds the checker role yet.", maker.name))
        req._push(maker)
        return req

    # ------------------------------------------------------------------ decide
    def _lock(self):
        """Row lock: a second checker deciding at the same moment waits, then finds it already decided."""
        try:
            self.env.cr.execute("SELECT id FROM ei_approval_request WHERE id IN %s FOR UPDATE NOWAIT", [tuple(self.ids)])
        except pg_errors.LockNotAvailable:
            raise UserError(_("Someone else is deciding this request right now. Reload in a moment."))
        self.invalidate_recordset()

    def _check_can_decide(self, verb):
        self.ensure_one()
        me = self.env.user
        if self.state != 'pending':
            who = self.decided_by.name or ''
            raise UserError(_("%(n)s is already %(s)s%(b)s. Nothing more to %(v)s.", n=self.name,
                              s=dict(STATES)[self.state].lower(), b=(' ' + _("by %s", who)) if who else '', v=verb))
        rec = self._record()
        if not rec:
            raise UserError(_("The document of this request no longer exists."))
        if me == self.maker_id or me == rec._ei_ap_maker():
            raise AccessError(_("Maker-checker: you submitted %s, so a different person must check it.", self.name))
        rule = self.rule_id
        if not self.env.su and me not in self._eligible(rec, rule, self.maker_id):
            raise AccessError(_("You are not an authorised checker for %(n)s (it needs: %(g)s).", n=self.name,
                                g=self.env.ref(rec._ei_ap_group).name))
        return rec

    def action_approve(self):
        for req in self:
            req._lock()
            rec = req._check_can_decide(_("approve"))
            if self._fingerprint(rec) != req.fingerprint:
                req._supersede(_("Its figures changed after it was submitted."))
                raise UserError(_("%s was changed after it was submitted, so this version cannot be approved. It goes back to the maker "
                                  "to resubmit.", req.name))
            try:
                rec.with_context(ei_ap_deciding=req.id)._ei_ap_do_approve()
            except (UserError, AccessError) as e:
                raise type(e)(_("%(n)s cannot be approved yet: %(e)s", n=req.name, e=e.args[0] if e.args else e))
            req.sudo().write({'state': 'approved', 'decided_at': fields.Datetime.now(), 'decided_by': self.env.user.id,
                              'decision_note': self.env.context.get('ei_ap_note') or False})
            req._event('approved', note=self.env.context.get('ei_ap_note'))
            rec._ei_ap_post(_("Approved by %s.", self.env.user.name))
            nxt = rec.with_context(ei_ap_deciding=req.id)._ei_ap_after_approved()
            if nxt:
                req._event('finalized', note=nxt)
            req._notify(req.maker_id, 'approved')
            req._push(*(req.eligible_user_ids | req.approver_id))
        return True

    def action_return(self, reason=None):
        return self._close_with('returned', reason)

    def action_reject(self, reason=None):
        return self._close_with('rejected', reason)

    def _close_with(self, outcome, reason):
        verb = _("return") if outcome == 'returned' else _("reject")
        if not (reason or '').strip():
            raise UserError(_("Write why you %s it; the maker sees your words.", verb))
        for req in self:
            req._lock()
            rec = req._check_can_decide(verb)
            rec = rec.with_context(ei_ap_deciding=req.id)
            rec._ei_ap_do_return(reason.strip()) if outcome == 'returned' else rec._ei_ap_do_reject(reason.strip())
            req.sudo().write({'state': outcome, 'decided_at': fields.Datetime.now(), 'decided_by': self.env.user.id,
                              'decision_note': reason.strip()})
            req._event(outcome, note=reason.strip())
            rec._ei_ap_post(_("%(o)s by %(u)s: %(r)s", o=dict(STATES)[outcome], u=self.env.user.name, r=reason.strip()))
            req._notify(req.maker_id, outcome)
            req._push(*(req.eligible_user_ids | req.approver_id))
        return True

    def action_withdraw(self):
        """The maker takes back a request nobody has decided yet (to correct it): the document returns to draft."""
        for req in self:
            req._lock()
            if req.state != 'pending':
                raise UserError(_("Only a pending request can be withdrawn."))
            if self.env.user != req.maker_id and not self.env.su:
                raise AccessError(_("Only the person who submitted it can withdraw it."))
            rec = req._record()
            rec.with_context(ei_ap_deciding=req.id)._ei_ap_do_return(_("Withdrawn by the maker"))
            req.sudo().write({'state': 'withdrawn', 'decided_at': fields.Datetime.now(), 'decided_by': self.env.user.id})
            req._event('withdrawn')
            rec._ei_ap_post(_("Withdrawn from approval by %s.", self.env.user.name))
            req._push(*(req.eligible_user_ids | req.approver_id))
        return True

    def action_reassign(self, user_id):
        """An administrator (or a manager) gives a request to another eligible checker; used when 'Assignment required'."""
        if not (self.env.user.has_group('base.group_system') or self.env.user.has_group('ei_management_dashboard.group_ei_management')):
            raise AccessError(_("Only an administrator or a manager can reassign a request."))
        user = self.env['res.users'].browse(int(user_id))
        for req in self:
            req._lock()
            if req.state != 'pending':
                raise UserError(_("Only a pending request can be reassigned."))
            rec = req.sudo()._record()                     # only its company and required role are read; nothing on it changes
            eligible = self._eligible(rec, req.rule_id, req.maker_id)
            if user not in eligible:
                raise UserError(_("%s is not an eligible checker for this document (role, company, or they made it).", user.name))
            old = req.approver_id
            req.sudo().write({'approver_id': user.id, 'needs_assignment': False, 'eligible_user_ids': [(6, 0, eligible.ids)]})
            req._event('reassigned', note=_("From %(a)s to %(b)s.", a=old.name or _("nobody"), b=user.name))
            req._notify(user, 'request')
            req._push(old, user, req.maker_id)
        return True

    def _supersede(self, why):
        """The document changed after submission: the request ends; the maker resubmits the new version."""
        for req in self.filtered(lambda r: r.state == 'pending'):
            req.sudo().write({'state': 'superseded', 'decided_at': fields.Datetime.now(), 'decision_note': why})
            req._event('superseded', note=why)
            req._notify(req.maker_id, 'returned')
            if req.approver_id:
                req._notify(req.approver_id, 'superseded')
            req._push(*(req.eligible_user_ids | req.approver_id | req.maker_id))

    # ------------------------------------------------------------------ timeline, notices, live counter
    def _event(self, kind, note=None, user=None):
        rec = self._record()
        self.env['ei.approval.event'].sudo().create({
            'request_id': self.id, 'kind': kind, 'user_id': (user or self.env.user).id, 'note': (note or '').strip() or False,
            'request_state': self.state, 'record_state': rec and rec._ei_ap_state_label() or False,
        })

    def _notify(self, user, kind):
        """One notice per person, request, kind and round: the same unchanged event never notifies twice."""
        if not user or user.id == 1:
            return
        N = self.env['ei.approval.notice'].sudo()
        if N.search_count([('user_id', '=', user.id), ('request_id', '=', self.id), ('kind', '=', kind), ('round', '=', self.round)]):
            return
        N.create({'user_id': user.id, 'request_id': self.id, 'kind': kind, 'round': self.round})
        self._push(user, toast=dict(NOTICES)[kind])

    def _push(self, *users, toast=None):
        for u in set(x for us in users for x in (us or [])):
            if u and u.id != 1:
                u.sudo()._bus_send('ei_approvals/changed', {'request_id': self.id if len(self) == 1 else False,
                                                            'toast': toast or False, 'name': self[:1].name or ''})

    # ------------------------------------------------------------------ centre and top bar (all run as the signed-in person)
    @api.model
    def _visible_domain(self):
        return [('company_id', 'in', self.env.companies.ids)]

    @api.model
    def counts(self):
        me = self.env.user.id
        base = [('state', '=', 'pending')]
        mine = self.search_count(base + [('approver_id', '=', me)])
        N = self.env['ei.approval.notice']
        return {
            'pending_for_me': mine,
            'overdue_for_me': self.search_count(base + [('approver_id', '=', me), ('is_overdue', '=', True)]),
            'unread': N.search_count([('user_id', '=', me), ('is_read', '=', False)]),
            'returned_to_me': self.search_count([('state', '=', 'returned'), ('maker_id', '=', me)]),
            'is_checker': bool(mine) or self.env['ei.approval.request']._user_is_checker(),
        }

    @api.model
    def _user_is_checker(self):
        groups = ['ei_contract_da.group_ei_contract_approver', 'ei_daily_orders.group_ei_order_approver', 'ei_cashbook.group_ei_cash_approver',
                  'ei_material_lifting.group_ei_lifting_reviewer', 'ei_management_dashboard.group_ei_management', 'base.group_system',
                  'ei_bank_operations.group_ei_bank_approver']
        return any(self.env.user.has_group(g) for g in groups)

    def _row(self):
        self.ensure_one()
        now = fields.Datetime.now()
        rec = self._record()
        return {
            'id': self.id, 'name': self.name, 'flow': self.flow, 'type': dict(FLOW_SELECTION)[self.flow],
            'party': self.partner_id.display_name or '', 'maker': self.maker_id.name, 'maker_id': self.maker_id.id,
            'approver': self.approver_id.name or '', 'approver_id': self.approver_id.id or False,
            'needs_assignment': self.needs_assignment and self.state == 'pending',
            'submitted': format_datetime(self.env, self.submitted_at, dt_format='dd MMM yyyy HH:mm'),
            'submitted_iso': fields.Datetime.to_string(self.submitted_at),
            'amount': self.amount, 'amount_text': format_amount(self.env, self.amount or 0.0, self.currency_id) if self.currency_id else '',
            'currency': self.currency_id.name or '', 'state': self.state, 'state_label': dict(STATES)[self.state],
            'priority': self.priority, 'overdue': self.is_overdue, 'round': self.round,
            'age_hours': round((now - self.submitted_at).total_seconds() / 3600.0, 1),
            'decided_by': self.decided_by.name or '', 'decision_note': self.decision_note or '',
            'record_state': rec and rec._ei_ap_state_label() or '',
            'can_decide': self.state == 'pending' and self.env.user != self.maker_id and self.env.user in self.eligible_user_ids,
            'mine': self.env.user == self.maker_id,
        }

    TABS = {
        'pending': lambda me: [('state', '=', 'pending'), ('approver_id', '=', me)],
        'urgent': lambda me: [('state', '=', 'pending'), '|', '|', ('urgent', '=', True), ('needs_assignment', '=', True), ('is_overdue', '=', True)],
        'returned': lambda me: [('state', 'in', ('returned', 'superseded'))],
        'approved': lambda me: [('state', '=', 'approved')],
        'rejected': lambda me: [('state', '=', 'rejected')],
        'mine': lambda me: [('maker_id', '=', me)],
        'all': lambda me: [],
        'history': lambda me: [('state', '!=', 'pending')],
    }
    SORTS = {'submitted': 'submitted_at', 'amount': 'amount', 'name': 'name', 'state': 'state', 'maker': 'maker_id', 'type': 'flow',
             'decided': 'decided_at', 'approver': 'approver_id', 'party': 'partner_id'}

    @api.model
    def center_data(self, tab='pending', search='', flow='', state='', date_from='', date_to='', sort='submitted', desc=True, offset=0, limit=25):
        me = self.env.user.id
        dom = list(self._visible_domain()) + self.TABS.get(tab, self.TABS['pending'])(me)
        if search:
            s = search.strip()
            dom += ['|', '|', '|', ('name', 'ilike', s), ('partner_id.name', 'ilike', s), ('maker_id.name', 'ilike', s), ('approver_id.name', 'ilike', s)]
        if flow:
            dom.append(('flow', '=', flow))
        if state:
            dom.append(('state', '=', state))
        if date_from:
            dom.append(('submitted_at', '>=', date_from + ' 00:00:00'))
        if date_to:
            dom.append(('submitted_at', '<=', date_to + ' 23:59:59'))
        order = '%s %s, id desc' % (self.SORTS.get(sort, 'submitted_at'), 'desc' if desc else 'asc')
        total = self.search_count(dom)
        rows = self.search(dom, order=order, offset=int(offset), limit=min(int(limit), 100))
        tabs = {k: self.search_count(list(self._visible_domain()) + f(me)) for k, f in self.TABS.items()}
        return {'rows': [r._row() for r in rows], 'total': total, 'tabs': tabs, 'counts': self.counts(),
                'flows': [{'key': k, 'label': v} for k, v in FLOW_SELECTION], 'states': [{'key': k, 'label': v} for k, v in STATES]}

    def review_data(self):
        """Everything a checker needs on one page. Read as the checker: the document's own access rules apply."""
        self.ensure_one()
        rec = self._record()
        if not rec:
            raise UserError(_("The document of this request no longer exists."))
        rec.check_access('read')
        docs = self.env['ei.documents'].list_for(rec._name, rec.id)
        history = self.search([('res_model', '=', self.res_model), ('res_id', '=', self.res_id)], order='round desc, id desc')
        events = self.env['ei.approval.event'].search([('request_id', 'in', history.ids)], order='at desc, id desc')
        eligible = self._eligible(rec.sudo(), self.rule_id, self.maker_id) if self.state == 'pending' else self.env['res.users']
        changed = self.state == 'pending' and self._fingerprint(rec) != self.fingerprint
        return {
            'row': self._row(), 'model': rec._name, 'res_id': rec.id, 'detail': rec._ei_ap_detail(),
            'submitted_facts': self.facts or {}, 'changed_since': changed, 'submit_note': self.submit_note or '',
            'documents': docs,
            'rounds': [dict(r._row(), current=(r == self)) for r in history],
            'timeline': [{'kind': e.kind, 'label': dict(EVENTS)[e.kind], 'who': _("System") if e.user_id.id == 1 else e.user_id.name, 'when': format_datetime(self.env, e.at, dt_format='dd MMM yyyy HH:mm'),
                          'note': e.note or '', 'round': e.request_id.round, 'record_state': e.record_state or ''} for e in events],
            'reassign_to': [{'id': u.id, 'name': u.name} for u in eligible]
            if (self.env.user.has_group('base.group_system') or self.env.user.has_group('ei_management_dashboard.group_ei_management')) else [],
            'can_withdraw': self.state == 'pending' and self.env.user == self.maker_id,
        }

    @api.model
    def decide(self, request_id, action, note=''):
        """The centre's buttons. Returns the refreshed review (or raises in plain words)."""
        req = self.browse(int(request_id)).exists()
        if not req:
            raise UserError(_("This request no longer exists."))
        req.check_access('read')
        if action == 'approve':
            req.with_context(ei_ap_note=(note or '').strip() or False).action_approve()
        elif action == 'return':
            req.action_return(note)
        elif action == 'reject':
            req.action_reject(note)
        elif action == 'withdraw':
            req.action_withdraw()
        else:
            raise UserError(_("Unknown action."))
        return req.review_data()

    @api.model
    def add_comment(self, request_id, note):
        req = self.browse(int(request_id)).exists()
        req.check_access('read')
        if not (note or '').strip():
            raise UserError(_("Write the comment first."))
        req._event('comment', note=note)
        req._record()._ei_ap_post(_("Review comment by %(u)s: %(n)s", u=self.env.user.name, n=note.strip()))
        others = (req.maker_id | req.approver_id) - self.env.user
        req._push(*others)
        return req.review_data()

    @api.model
    def open_record_action(self, request_id):
        req = self.browse(int(request_id)).exists()
        req.check_access('read')
        rec = req._record()
        rec.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': rec._name, 'res_id': rec.id, 'views': [[False, 'form']], 'target': 'current'}

    # ------------------------------------------------------------------ overdue
    @api.model
    def _cron_escalate(self):
        due = self.sudo().search([('state', '=', 'pending'), ('due_at', '<', fields.Datetime.now()), ('escalated_at', '=', False)])
        for req in due:
            req.sudo().write({'escalated_at': fields.Datetime.now(), 'urgent': True})
            req.sudo()._event('escalated', note=_("Waiting since %s.", format_datetime(self.env, req.submitted_at)),
                              user=self.env.ref('base.user_root'))
            group = req.rule_id.escalate_group_id or self.env.ref('ei_management_dashboard.group_ei_management')
            for u in self.env['res.users'].sudo().search([('share', '=', False), ('all_group_ids', 'in', [group.id])]):
                if u != req.maker_id:
                    req._notify(u, 'escalated')
            if req.approver_id:
                req._notify(req.approver_id, 'escalated')


class EiApprovalEvent(models.Model):
    _name = 'ei.approval.event'
    _description = 'Approval timeline entry'
    _order = 'at desc, id desc'

    request_id = fields.Many2one('ei.approval.request', required=True, ondelete='cascade', index=True, readonly=True)
    kind = fields.Selection(EVENTS, required=True, readonly=True)
    user_id = fields.Many2one('res.users', required=True, readonly=True)
    at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    note = fields.Text(readonly=True)
    request_state = fields.Char(readonly=True)
    record_state = fields.Char('Document stage', readonly=True)

    def write(self, vals):
        raise AccessError(_("The approval timeline cannot be changed."))

    def unlink(self):
        raise AccessError(_("The approval timeline cannot be deleted."))


class EiApprovalNotice(models.Model):
    _name = 'ei.approval.notice'
    _description = 'Approval notification'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, index=True, readonly=True)
    request_id = fields.Many2one('ei.approval.request', required=True, ondelete='cascade', index=True, readonly=True)
    kind = fields.Selection(NOTICES, required=True, readonly=True)
    round = fields.Integer(readonly=True)
    is_read = fields.Boolean(index=True)

    _once = models.Constraint('unique(user_id, request_id, kind, round)', 'This notification was already sent.')

    @api.model
    def inbox(self, limit=12):
        me = self.env.user
        rows = self.search([('user_id', '=', me.id)], limit=int(limit))
        out = []
        for n in rows:
            r = n.request_id
            out.append({'id': n.id, 'kind': n.kind, 'label': dict(NOTICES)[n.kind], 'read': n.is_read, 'request_id': r.id,
                        'name': r.name, 'type': dict(FLOW_SELECTION)[r.flow], 'maker': r.maker_id.name, 'party': r.partner_id.display_name or '',
                        'when': format_datetime(self.env, n.create_date, dt_format='dd MMM HH:mm'),
                        'amount_text': format_amount(self.env, r.amount or 0.0, r.currency_id) if r.currency_id and r.amount else '',
                        'state': r.state, 'overdue': r.is_overdue, 'urgent': r.priority == 'urgent', 'note': r.decision_note or ''})
        return {'items': out, 'counts': self.env['ei.approval.request'].counts()}

    @api.model
    def mark_read(self, ids=None):
        dom = [('user_id', '=', self.env.user.id), ('is_read', '=', False)]
        if ids:
            dom.append(('id', 'in', [int(i) for i in ids]))
        self.search(dom).sudo().write({'is_read': True})
        self.env.user._bus_send('ei_approvals/changed', {'request_id': False, 'toast': False, 'name': ''})
        return self.env['ei.approval.request'].counts()
