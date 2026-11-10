"""The second-person steps that already existed in other modules, brought into the same requests, notifications and centre:
bank statement approval and posting, supplier-invoice mismatch acceptance, parent-statement sign-off, the daily cash count close,
rate-formula approval and the day / month-end close.

Nothing about how these documents work changes. A request is opened by itself as soon as a document is in the state where it waits
for a second person (the same states My Work already uses); the checker decides in the approvals centre or on the document, and either
way the document's own method runs, as the checker, with all its own checks (its role, its maker-checker rule, its blockers). The engine's
rules apply on top (never the maker, the role, the company, still pending, unchanged since it was opened)."""
import time

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_LAST_SYNC = {}
SYNC_EVERY = 20          # seconds between two background checks per database (the centre and the counter trigger them)


class EiApprovalQueueMixin(models.AbstractModel):
    """For documents whose second-person step is always on (it is part of how they work, not an optional policy)."""
    _name = 'ei.approval.queue.mixin'
    _inherit = 'ei.approval.mixin'
    _description = 'A second-person step shown in the approvals centre'
    _ei_ap_method = None                 # the document's own decision method
    _ei_ap_done = {}                     # document state -> request outcome when it was decided on the document itself
    _ei_ap_decider = None                # the field holding who decided on the document
    _ei_ap_can_reject = False
    _ei_ap_note_field = None             # where the checker's note goes when the method insists on one
    _ei_ap_maker_field = 'create_uid'

    def _approval_required(self):
        return True

    def _ei_ap_submittable(self):
        return False                     # opened by itself; there is no separate "submit" button

    def _ei_ap_maker(self):
        return self[self._ei_ap_maker_field] if self._ei_ap_maker_field in self._fields and self[self._ei_ap_maker_field] else self.create_uid

    def _ei_ap_ready(self):
        """Waiting for a second person right now (state domain plus anything only Python can tell)."""
        return True

    @api.model
    def _ei_ap_waiting_domain(self):
        return [('state', 'in', list(self._ei_ap_waiting))]

    def _ei_ap_fingerprint_values(self):
        return {'state': self.state, 'write_date': str(self.write_date)}

    def _ei_ap_detail(self):
        ev = self.env['ei.approval.evidence'].get_evidence(self._name, self.id, self._ei_ap_method) or {}
        head = [[f['label'], f['value']] for f in ev.get('facts', [])]
        return {'head': head, 'columns': [], 'rows': [], 'warnings': ev.get('warnings', []), 'totals': []}

    def _ei_ap_do_approve(self):
        note = self.env.context.get('ei_ap_note')
        if note and self._ei_ap_note_field and not (self[self._ei_ap_note_field] or '').strip():
            self.with_context(ei_system=True).write({self._ei_ap_note_field: note})
        return getattr(self.with_context(ei_ap_deciding=self.env.context.get('ei_ap_deciding') or True), self._ei_ap_method)()

    def _ei_ap_do_return(self, reason):
        return True                      # the document stays as it is; the maker sees the reason and corrects it

    def _ei_ap_do_reject(self, reason):
        raise UserError(_("This kind of document cannot be rejected from here; return it to the person who prepared it."))

    def _ei_ap_after_approved(self):
        return _("Done: %s.", self._ei_ap_state_label())


class EiApprovalQueueRoute(models.AbstractModel):
    _inherit = 'ei.approval.queue.mixin'

    def _ei_ap_queue_route(self, call_original):
        """The document's own button: go through the request (opened now if the document waits), deciding as the signed-in person."""
        Req = self.env['ei.approval.request']
        for r in self:
            req = Req._pending_for(r)
            if not req:
                if not r.filtered_domain(r._ei_ap_waiting_domain()):
                    call_original(r)                     # let the document say in its own words why not
                    continue
                req = Req.sudo()._submit(r.sudo())
            Req.browse(req.id).with_context(ei_ap_deciding=False).action_approve()
        return True


class EiBankImport(models.Model):
    _name = 'ei.bank.import'
    _inherit = ['ei.bank.import', 'ei.approval.queue.mixin']
    _ei_ap_flow = 'bank'
    _ei_ap_group = 'ei_bank_operations.group_ei_bank_approver'
    _ei_ap_waiting = ('received', 'validated', 'proposed')
    _ei_ap_method = 'action_approve'
    _ei_ap_done = {'approved': 'approved', 'posted': 'approved', 'rejected': 'rejected'}
    _ei_ap_decider = 'approved_by'
    _ei_ap_can_reject = True
    _ei_ap_maker_field = 'imported_by'

    def _ei_ap_ready(self):
        return not self.n_open and bool(self.line_ids.filtered(lambda l: l.state in ('verified', 'unidentified')))

    def _ei_ap_info(self):
        return {'name': _("Bank statement %s", self.name), 'partner': self.env['res.partner'], 'currency': self.currency_id,
                'amount': sum(self.line_ids.filtered(lambda l: l.state in ('verified', 'unidentified')).mapped('amount'))}

    def _ei_ap_do_reject(self, reason):
        self.message_post(body=_("Rejected at approval: %s", reason))
        return self.with_context(ei_ap_deciding=True).action_reject()

    def action_approve(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_approve()
        return self._ei_ap_queue_route(lambda recs: super(EiBankImport, recs).action_approve())


class EiSupplierIntake(models.Model):
    _name = 'ei.supplier.intake'
    _inherit = ['ei.supplier.intake', 'ei.approval.queue.mixin']
    _ei_ap_flow = 'intake'
    _ei_ap_group = 'ei_invoice_extensions.group_ei_invoice_approver'
    _ei_ap_waiting = ('mismatch',)
    _ei_ap_method = 'action_override'
    _ei_ap_done = {'reviewed': 'approved', 'billed': 'approved', 'cancelled': 'rejected'}
    _ei_ap_decider = 'reviewed_by'
    _ei_ap_can_reject = True
    _ei_ap_note_field = 'review_note'
    _ei_ap_maker_field = 'maker_id'

    def _ei_ap_info(self):
        return {'name': _("Supplier invoice %s", self.invoice_number or self.display_name), 'partner': self.partner_id,
                'amount': self.stated_total, 'currency': self.currency_id}

    def _ei_ap_detail(self):
        d = super()._ei_ap_detail()
        if self.issue_text:
            d['warnings'] = list(d.get('warnings') or []) + [x for x in self.issue_text.split('\n') if x.strip()]
        return d

    def _ei_ap_do_reject(self, reason):
        self.message_post(body=_("Rejected at approval: %s", reason))
        return self.with_context(ei_ap_deciding=True).action_cancel()

    def action_override(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_override()
        return self._ei_ap_queue_route(lambda recs: super(EiSupplierIntake, recs).action_override())


class EiParentStatement(models.Model):
    _name = 'ei.parent.statement'
    _inherit = ['ei.parent.statement', 'ei.approval.queue.mixin']
    _ei_ap_flow = 'recon'
    _ei_ap_group = 'ei_parent_reconciliation.group_ei_recon_approver'
    _ei_ap_waiting = ('resolved',)
    _ei_ap_method = 'action_sign'
    _ei_ap_done = {'signed': 'approved', 'rejected': 'rejected'}
    _ei_ap_decider = 'signed_by'
    _ei_ap_maker_field = 'imported_by'

    def _ei_ap_info(self):
        return {'name': _("Parent statement %s", self.display_name), 'partner': self.partner_id, 'amount': self.statement_total,
                'currency': self.currency_id}

    def action_sign(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_sign()
        return self._ei_ap_queue_route(lambda recs: super(EiParentStatement, recs).action_sign())


class EiCashCount(models.Model):
    _name = 'ei.cash.count'
    _inherit = ['ei.cash.count', 'ei.approval.queue.mixin']
    _ei_ap_flow = 'cashcount'
    _ei_ap_group = 'ei_cashbook.group_ei_cash_approver'
    _ei_ap_waiting = ('draft',)
    _ei_ap_method = 'action_close'
    _ei_ap_done = {'closed': 'approved'}
    _ei_ap_decider = 'closed_by'
    _ei_ap_note_field = 'discrepancy_note'
    _ei_ap_maker_field = 'custodian_id'

    def _ei_ap_info(self):
        return {'name': self.display_name, 'partner': self.env['res.partner'], 'amount': self.counted_amount, 'currency': self.currency_id}

    def _ei_ap_detail(self):
        d = super()._ei_ap_detail()
        d['head'] = [[_("Cash box"), self.journal_id.display_name or ''], [_("Day"), str(self.date or '')],
                     [_("Counted by"), self.custodian_id.name or ''], [_("Note"), self.discrepancy_note or '']]
        d['totals'] = [[_("Counted"), self._ei_ap_money(self.counted_amount, self.currency_id)],
                       [_("Book now"), self._ei_ap_money(self.now_book, self.currency_id)],
                       [_("Difference now"), self._ei_ap_money(self.now_difference, self.currency_id)]]
        return d

    def action_close(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_close()
        return self._ei_ap_queue_route(lambda recs: super(EiCashCount, recs).action_close())


class EiFormula(models.Model):
    _name = 'ei.formula.definition'
    _inherit = ['ei.formula.definition', 'ei.approval.queue.mixin']
    _ei_ap_flow = 'formula'
    _ei_ap_group = 'ei_contract_da.group_ei_formula_approver'
    _ei_ap_waiting = ('draft',)
    _ei_ap_method = 'action_approve'
    _ei_ap_done = {'approved': 'approved', 'retired': 'withdrawn'}
    _ei_ap_decider = 'approved_by'

    def _ei_ap_ready(self):
        return bool(self.step_ids) and bool(self.test_ids)

    def _ei_ap_info(self):
        return {'name': _("Formula %(c)s v%(v)s", c=self.code, v=self.version), 'partner': self.env['res.partner'], 'amount': 0.0,
                'currency': self.env.company.currency_id}

    def action_approve(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_approve()
        return self._ei_ap_queue_route(lambda recs: super(EiFormula, recs).action_approve())


class EiClose(models.Model):
    _name = 'ei.close'
    _inherit = ['ei.close', 'ei.approval.queue.mixin']
    _ei_ap_flow = 'close'
    _ei_ap_group = 'account.group_account_manager'
    _ei_ap_waiting = ('open',)
    _ei_ap_method = 'action_sign'
    _ei_ap_done = {'signed': 'approved'}
    _ei_ap_decider = 'signed_by'

    def _ei_ap_ready(self):
        return bool(self.refreshed_at) and not self.env['ei.close.item'].sudo().search_count(
            [('close_id', '=', self.id), ('status', '=', 'blocker'), ('waived_by', '=', False)])

    def _ei_ap_info(self):
        return {'name': self.display_name, 'partner': self.env['res.partner'], 'amount': 0.0, 'currency': self.company_id.currency_id}

    def _ei_ap_detail(self):
        return {'head': [[_("Close"), self.display_name], [_("Period"), '%s - %s' % (self.date_from, self.date_to)],
                         [_("Blockers"), str(self.n_blockers)], [_("Waived"), str(self.n_waived)], [_("Warnings"), str(self.n_warnings)],
                         [_("Last checked"), '%s, %s' % (self.refreshed_by.name or '', self.refreshed_at or '')]],
                'columns': [_("Check"), _("Status"), _("Count"), _("Detail")],
                'rows': [[i.label, i.status, str(i.count), i.detail or ''] for i in self.item_ids], 'totals': []}

    def action_sign(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_sign()
        return self._ei_ap_queue_route(lambda recs: super(EiClose, recs).action_sign())


QUEUE_MODELS = ['ei.bank.import', 'ei.supplier.intake', 'ei.parent.statement', 'ei.cash.count', 'ei.formula.definition', 'ei.close']


class EiApprovalRequestQueue(models.Model):
    _inherit = 'ei.approval.request'

    @api.model
    def _queue_sync(self, force=False):
        """Open a request for every document that now waits for a second person, and close the ones decided on the document."""
        key = self.env.cr.dbname
        if not force and time.time() - _LAST_SYNC.get(key, 0) < SYNC_EVERY:
            return
        _LAST_SYNC[key] = time.time()
        Req = self.sudo()
        for model in QUEUE_MODELS:
            if model not in self.env:
                continue
            M = self.env[model].sudo()
            waiting = M.search(M._ei_ap_waiting_domain()).filtered(lambda r: r._ei_ap_ready())
            pending = Req.search([('res_model', '=', model), ('state', '=', 'pending')])
            have = set(pending.mapped('res_id'))
            for rec in waiting.filtered(lambda r: r.id not in have):
                last = Req._latest_for(rec)
                if last and last.state in ('returned', 'rejected', 'withdrawn', 'superseded') and last.decided_at \
                        and rec.write_date and rec.write_date <= last.decided_at:
                    continue                                    # returned and not touched since: wait for the maker's correction
                Req._submit(rec)
            ids = set(waiting.ids)
            for req in pending.filtered(lambda q: q.res_id not in ids):
                rec = M.browse(req.res_id).exists()
                outcome = rec and M._ei_ap_done.get(rec.state) or 'withdrawn'
                who = rec and M._ei_ap_decider and rec[M._ei_ap_decider] or (rec.write_uid if rec else self.env['res.users'])
                req.write({'state': outcome, 'decided_at': fields.Datetime.now(), 'decided_by': who.id or False,
                           'decision_note': _("Decided on the document itself.") if outcome != 'withdrawn' else _("No longer waiting for a second person.")})
                req.with_user(who.id if who else self.env.uid)._event(outcome if outcome in ('approved', 'rejected', 'withdrawn') else 'withdrawn',
                                                                    note=req.decision_note)
                if outcome in ('approved', 'rejected'):
                    req._notify(req.maker_id, outcome)
                req._push(*(req.eligible_user_ids | req.approver_id | req.maker_id))

    @api.model
    def _cron_queue_sync(self):
        self._queue_sync(force=True)

    @api.model
    def counts(self):
        self._queue_sync()
        return super().counts()

    @api.model
    def center_data(self, *args, **kwargs):
        self._queue_sync()
        return super().center_data(*args, **kwargs)

    def _row(self):
        row = super()._row()
        row['can_reject'] = getattr(type(self.env[self.res_model]), '_ei_ap_can_reject', True)
        row['queue'] = self.res_model in QUEUE_MODELS
        return row
