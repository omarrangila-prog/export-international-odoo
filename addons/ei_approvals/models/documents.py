"""The five documents the client checks maker-checker, connected to the approval engine.

Each document keeps its own states and its own checks; this file only adds:
  * submit  -> a request is created and assigned the moment the document's own 'submit' step runs (when approval is on);
  * approve -> the document's own approve/verify method can only run through a pending request decided by an eligible checker who is
               not the maker (a direct call, an old browser tab or a programming interface is routed through the same request);
  * return  -> the document goes back to draft for the maker to correct and resubmit;
  * reject  -> the document is cancelled (or rejected) with the checker's reason;
  * after approval -> the next business stage: a contract becomes active; an approved DA prepares today's daily order request.
Why each document's approval boundary is where it is: see docs/maker_checker.md."""
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import format_amount


class EiApprovalMixin(models.AbstractModel):
    _name = 'ei.approval.mixin'
    _description = 'Maker-checker approval on a document'
    _ei_ap_flow = None
    _ei_ap_group = None                       # the role the document itself demands of its checker
    _ei_ap_waiting = ()                       # the document states in which it waits for a checker

    approval_state = fields.Selection([('none', "Not submitted"), ('pending', "Pending approval"), ('approved', "Approved"),
                                       ('returned', "Returned for correction"), ('rejected', "Rejected"), ('withdrawn', "Withdrawn"),
                                       ('superseded', "Changed after submission")],
                                      compute='_compute_approval', string='Approval status')
    approval_request_id = fields.Many2one('ei.approval.request', compute='_compute_approval', string='Approval request')
    approval_approver_id = fields.Many2one('res.users', compute='_compute_approval', string='Assigned checker')
    approval_note = fields.Text(compute='_compute_approval', string="Checker's note")
    approval_needs_assignment = fields.Boolean('Assignment required', compute='_compute_approval')
    approval_can_submit = fields.Boolean('Ready to submit for approval', compute='_compute_approval')

    def _compute_approval(self):
        Req = self.env['ei.approval.request'].sudo()
        for r in self:
            req = Req._latest_for(r) if r.id else Req
            r.approval_request_id = req.id or False
            r.approval_state = req.state if req else 'none'
            r.approval_approver_id = req.approver_id.id or False if req else False
            r.approval_note = req.decision_note or False if req else False
            r.approval_needs_assignment = bool(req) and req.state == 'pending' and req.needs_assignment
            r.approval_can_submit = bool(r.id) and r._approval_required() and r._ei_ap_submittable() and not (req and req.state == 'pending')

    # ---- what every document provides (overridden below)
    def _ei_ap_maker(self):
        return self.maker_id if 'maker_id' in self._fields and self.maker_id else self.create_uid

    def _ei_ap_state_label(self):
        f = self._fields['state']
        return dict(f._description_selection(self.env)).get(self.state, self.state)

    def _ei_ap_submittable(self):
        return self.state == 'draft'

    def _ei_ap_post(self, body):
        if 'message_ids' in self._fields:
            self.sudo().message_post(body=body, subtype_xmlid='mail.mt_note', author_id=self.env.user.partner_id.id)

    def _ei_ap_money(self, v, cur=None):
        cur = cur or self._ei_ap_info().get('currency') or self.env.company.currency_id
        return format_amount(self.env, v or 0.0, cur)

    def _ei_ap_facts(self):
        """A frozen copy of what was submitted (shown beside the live document)."""
        d = self._ei_ap_detail()
        return {'head': d['head'], 'totals': d.get('totals', [])}

    # ---- the buttons
    def action_submit_for_approval(self):
        for r in self:
            if not r._approval_required():
                raise UserError(_("Approval is switched off for this kind of document; use Save & Continue."))
            if self.env['ei.approval.request']._pending_for(r):
                raise UserError(_("%s is already waiting for approval.", r.display_name))
            r._ei_ap_do_submit()
        return True

    def action_open_approval(self):
        self.ensure_one()
        req = self.env['ei.approval.request'].sudo()._latest_for(self)
        return {'type': 'ir.actions.client', 'tag': 'ei_approvals.center', 'name': _("Approvals"),
                'params': {'request_id': req.id or False, 'tab': 'all'}}

    def _ei_ap_route_approve(self):
        """Every approve/verify while approval is on goes through a pending request and its checker rules. A document that reached
        its waiting state before this module existed gets its request now (the maker-checker rule applies to it all the same)."""
        Req = self.env['ei.approval.request']
        todo = self.filtered(lambda r: r._approval_required())
        for r in todo:
            req = Req._pending_for(r)
            if not req:
                last = Req._latest_for(r)
                if last and last.state in ('returned', 'superseded', 'withdrawn', 'rejected'):
                    raise UserError(_("%(n)s was %(s)s; the maker corrects it and submits it again before anyone can approve it.",
                                      n=r.display_name, s=dict(last._fields['state']._description_selection(self.env))[last.state].lower()))
                if r.state not in r._ei_ap_waiting:
                    raise UserError(_("%(n)s is %(s)s; it has to be submitted for approval first.", n=r.display_name, s=r._ei_ap_state_label()))
                req = Req._submit(r)
            req.with_context(ei_ap_deciding=False).action_approve()
        rest = self - todo
        if rest:
            rest.with_context(ei_ap_deciding=True)._ei_ap_do_approve()
        return True


class EiContract(models.Model):
    _name = 'ei.contract'
    _inherit = ['ei.contract', 'ei.approval.mixin']
    _ei_ap_flow = 'contract'
    _ei_ap_group = 'ei_contract_da.group_ei_contract_approver'
    _ei_ap_waiting = ('reviewed',)

    def _ei_ap_info(self):
        amount = sum(l.ordered_mtl * l.purchase_rate for l in self.line_ids)
        return {'name': _("Contract %(n)s (%(r)s)", n=self.name, r=self.contract_ref or ''), 'partner': self.parent_partner_id,
                'amount': amount, 'currency': self.currency_id}

    def _ei_ap_fingerprint_values(self):
        return {'parent': self.parent_partner_id.id, 'cur': self.currency_id.id, 'ref': self.contract_ref,
                'lines': sorted([(l.product_id.id, l.ordered_mtl, l.purchase_rate, l.sale_rate, l.basic_rate, l.formula_id.id,
                                  sorted((p.key, p.value) for p in l.param_ids)) for l in self.line_ids])}

    def _ei_ap_detail(self):
        cur = self.currency_id
        return {
            'head': [[_("Contract"), '%s (%s)' % (self.name, self.contract_ref or '')], [_("Parent company"), self.parent_partner_id.display_name or ''],
                     [_("Type"), dict(self._fields['contract_type']._description_selection(self.env)).get(self.contract_type, '')],
                     [_("Currency"), cur.name or ''], [_("Valid"), '%s - %s' % (self.valid_from or '', self.valid_to or '')],
                     [_("Revision"), str(self.revision or 0)]],
            'columns': [_("Material"), _("MTL"), _("Basic rate"), _("Purchase / MTL"), _("Sale / MTL"), _("Spread / MTL"), _("Formula")],
            'rows': [[l.product_id.display_name, f"{l.ordered_mtl:,.3f}", self._ei_ap_money(l.basic_rate, cur), self._ei_ap_money(l.purchase_rate, cur),
                      self._ei_ap_money(l.sale_rate, cur), self._ei_ap_money(l.sale_rate - l.purchase_rate, cur),
                      l.formula_id and '%s v%s' % (l.formula_id.code, l.formula_id.version) or ''] for l in self.line_ids],
            'totals': [[_("Purchase value"), self._ei_ap_money(sum(l.ordered_mtl * l.purchase_rate for l in self.line_ids), cur)],
                       [_("Expected gross spread"), self._ei_ap_money(sum(l.ordered_mtl * (l.sale_rate - l.purchase_rate) for l in self.line_ids), cur)]],
        }

    def action_review(self):
        res = super().action_review()
        for r in self.filtered(lambda x: x.state == 'reviewed' and x._approval_required()):
            self.env['ei.approval.request']._submit(r)
        return res

    def _ei_ap_do_submit(self):
        return self.action_review()

    def action_approve(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_approve()
        return self._ei_ap_route_approve()

    def _ei_ap_do_approve(self):
        return self.action_approve()

    def action_activate(self):
        """An approved contract becomes active at once (its next stage); activating one that already is changes nothing."""
        todo = self.filtered(lambda r: r.state != 'active')
        return super(EiContract, todo).action_activate() if todo else True

    def _ei_ap_after_approved(self):
        if self.state == 'approved':
            self.action_activate()
            return _("The contract is active: delivery advices can be fed against it.")
        return False

    def _ei_ap_do_return(self, reason):
        self._sys({'state': 'draft', 'reviewed_by': False})

    def _ei_ap_do_reject(self, reason):
        self.action_cancel(reason=_("Rejected at approval: %s", reason))


class EiDa(models.Model):
    _name = 'ei.da'
    _inherit = ['ei.da', 'ei.approval.mixin']
    _ei_ap_flow = 'da'
    _ei_ap_group = 'ei_contract_da.group_ei_contract_approver'
    _ei_ap_waiting = ('under_review',)

    def _ei_ap_info(self):
        customers = self.line_ids.customer_id
        return {'name': self.name if (self.name or '').upper().startswith('DA') else _("DA %s", self.name), 'partner': customers if len(customers) == 1 else self.parent_partner_id,
                'amount': sum(l.mtl * l.purchase_rate for l in self.line_ids), 'currency': self.contract_id.currency_id}

    def _ei_ap_fingerprint_values(self):
        f = lambda l, n: l[n] if n in l._fields else None
        return {'contract': self.contract_id.id, 'date': self.date, 'lines': sorted(
            [(l.contract_line_id.id, l.mtl, l.purchase_rate, l.sale_rate, l.customer_id.id, f(l, 'coil_no'), f(l, 'feeding_method'),
              f(l, 'cn_amount'), f(l, 'customer_code_id') and l.customer_code_id.id) for l in self.line_ids], key=str)}

    def _ei_ap_detail(self):
        cur = self.contract_id.currency_id
        lines = self.line_ids
        feed = 'feeding_method' in lines._fields
        head = [[_("DA"), self.name], [_("Contract"), '%s (%s)' % (self.contract_id.name, self.contract_id.contract_ref or '')],
                [_("Parent company"), self.parent_partner_id.display_name or ''], [_("DA date"), str(self.date or '')], [_("Currency"), cur.name or '']]
        if 'printed_customer' in self._fields and self.printed_customer:
            head.append([_("Customer printed on the DA"), self.printed_customer])
        if 'fx_text' in self._fields and self.fx_text:
            head.append([_("Exchange rate"), self.fx_text])
        cols = [_("Coil"), _("Customer"), _("Code"), _("Method"), _("MTL"), _("Purchase / MTL"), _("Sale / MTL"), _("CN / MTL"), _("Spread / MTL"), _("Coil spread")]
        rows = []
        for l in lines:
            spread = l.sale_rate - l.purchase_rate
            rows.append([l.coil_no or l.product_id.display_name if feed else l.product_id.display_name, l.customer_id.display_name or '',
                         (l.customer_code_id.legacy_code or '') if feed else '',
                         (dict(l._fields['feeding_method']._description_selection(self.env)).get(l.feeding_method, '') if feed else ''),
                         f"{l.mtl:,.3f}", self._ei_ap_money(l.purchase_rate, cur), self._ei_ap_money(l.sale_rate, cur),
                         self._ei_ap_money(l.net_cn, cur) if feed and l.net_cn else '', self._ei_ap_money(spread, cur), self._ei_ap_money(spread * l.mtl, cur)])
        issues = sorted(set(l.code_issue for l in lines if feed and l.code_issue))
        keep = [i for i in range(len(cols)) if any(r[i] not in ('', None) for r in rows)] if rows else list(range(len(cols)))
        cols, rows = [cols[i] for i in keep], [[r[i] for i in keep] for r in rows]
        return {'head': head, 'columns': cols, 'rows': rows, 'warnings': issues,
                'totals': [[_("Coils"), str(len(lines))], [_("MTL"), f"{sum(lines.mapped('mtl')):,.3f}"],
                           [_("Purchase value"), self._ei_ap_money(sum(l.mtl * l.purchase_rate for l in lines), cur)],
                           [_("Expected gross spread"), self._ei_ap_money(sum(l.mtl * (l.sale_rate - l.purchase_rate) for l in lines), cur)]]}

    def action_review(self):
        res = super().action_review()
        for r in self.filtered(lambda x: x.state == 'under_review' and x._approval_required()):
            self.env['ei.approval.request']._submit(r)
        return res

    def _ei_ap_do_submit(self):
        return self.action_review()

    def action_approve(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_approve()
        return self._ei_ap_route_approve()

    def _ei_ap_do_approve(self):
        return self.action_approve()

    def _ei_ap_after_approved(self):
        """An approved DA prepares today's daily order request (once; a problem with the order never undoes the approval)."""
        # only a DA fed coil by coil in the feeding desk goes on by itself (the client's simple workflow: DA -> today's order);
        # other DAs keep the order desk's own "Generate daily order" step, with its own date and partial quantities
        if self.state != 'approved' or 'ei.daily.order' not in self.env or 'feeding_method' not in self.line_ids._fields \
                or not self.line_ids.filtered('feeding_method'):
            return False
        Order = self.env['ei.daily.order']
        if not Order.has_access('create'):
            return _("Approved. The order desk prepares today's daily order request from it.")
        try:
            with self.env.cr.savepoint():
                before = Order.search([('company_id', '=', self.company_id.id), ('parent_partner_id', '=', self.parent_partner_id.id),
                                       ('date', '=', fields.Date.context_today(self))], limit=1)
                order = Order.generate_from_da(self)
                if order and not before:
                    order.with_context(ei_system=True).write({'maker_id': self._ei_ap_maker().id})     # prepared from this maker's DA
        except UserError as e:
            return _("Today's daily order request could not be prepared: %s", e.args[0] if e.args else e)
        if not order:
            return False
        if order._approval_required() and order.state == 'draft':
            order._ei_ap_refresh()
        return _("Daily order request %s prepared.", order.display_name)

    def _ei_ap_do_return(self, reason):
        self._sys({'state': 'draft'})

    def _ei_ap_do_reject(self, reason):
        self.action_cancel(reason=_("Rejected at approval: %s", reason))


class EiDailyOrder(models.Model):
    _name = 'ei.daily.order'
    _inherit = ['ei.daily.order', 'ei.approval.mixin']
    _ei_ap_flow = 'order'
    _ei_ap_group = 'ei_daily_orders.group_ei_order_approver'
    _ei_ap_waiting = ('draft',)

    def _ei_ap_info(self):
        lines = self.line_ids
        cur = lines[:1].currency_id if lines and 'currency_id' in lines._fields else self.company_id.currency_id
        return {'name': _("Daily order %s", self.name), 'partner': self.parent_partner_id,
                'amount': sum(l.requested_mtl * (l.purchase_rate or 0.0) for l in lines), 'currency': cur}

    def _ei_ap_fingerprint_values(self):
        return {'parent': self.parent_partner_id.id, 'date': self.date,
                'lines': sorted([(l.da_line_id.id, l.requested_mtl) for l in self.line_ids])}

    def _ei_ap_detail(self):
        cur = self._ei_ap_info()['currency']
        return {'head': [[_("Daily order"), self.name], [_("Parent company"), self.parent_partner_id.display_name or ''], [_("Date"), str(self.date or '')]],
                'columns': [_("DA"), _("Customer"), _("Requested MTL"), _("Purchase / MTL"), _("Sale / MTL")],
                'rows': [[l.da_line_id.da_id.name, l.da_line_id.customer_id.display_name or '', f"{l.requested_mtl:,.3f}",
                          self._ei_ap_money(l.purchase_rate, cur), self._ei_ap_money(l.sale_rate, cur)] for l in self.line_ids],
                'totals': [[_("Requested MTL"), f"{sum(self.line_ids.mapped('requested_mtl')):,.3f}"],
                           [_("Purchase value"), self._ei_ap_money(self._ei_ap_info()['amount'], cur)]]}

    def _ei_ap_do_submit(self):
        if not self.line_ids:
            raise UserError(_("Add at least one line before submitting."))
        return self.env['ei.approval.request']._submit(self)

    def _ei_ap_refresh(self):
        """The order changed while waiting (a new DA added its lines): the old request ends and the new version is submitted."""
        Req = self.env['ei.approval.request']
        for o in self:
            req = Req._pending_for(o)
            if req and Req._fingerprint(o) != req.fingerprint:
                req._supersede(_("Lines were added or changed."))
                Req.with_context(ei_ap_implicit=True)._submit(o)
            elif not req and o.line_ids:
                Req.with_context(ei_ap_implicit=True)._submit(o)

    def _ei_ap_check_changed(self):
        Req = self.env['ei.approval.request']
        for o in self:
            req = Req._pending_for(o)
            if req and not self.env.context.get('ei_ap_deciding') and Req._fingerprint(o) != req.fingerprint:
                req._supersede(_("Lines were changed after submission."))

    def action_confirm(self):
        todo = self.filtered(lambda o: o.state == 'draft' and o._approval_required())
        for o in todo:
            if not self.env['ei.approval.request']._pending_for(o):
                o._ei_ap_do_submit()
        return super(EiDailyOrder, self - todo).action_confirm() if self - todo else True

    def action_approve(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_approve()
        return self._ei_ap_route_approve()

    def _ei_ap_do_approve(self):
        return self.action_approve()

    def _ei_ap_after_approved(self):
        return _("The order request is approved: print it or email it to the parent company.") if self.state == 'approved' else False

    def _ei_ap_do_return(self, reason):
        return True                                   # it stays a draft; the request records the reason

    def _ei_ap_do_reject(self, reason):
        self.action_cancel(reason=_("Rejected at approval: %s", reason))


class EiDailyOrderLine(models.Model):
    _inherit = 'ei.daily.order.line'

    def write(self, vals):
        res = super().write(vals)
        if 'requested_mtl' in vals or 'da_line_id' in vals:
            self.order_id._ei_ap_check_changed()
        return res


class EiCashVoucher(models.Model):
    _name = 'ei.cash.voucher'
    _inherit = ['ei.cash.voucher', 'ei.approval.mixin']
    _ei_ap_flow = 'cash'
    _ei_ap_group = 'ei_cashbook.group_ei_cash_approver'
    _ei_ap_waiting = ('submitted',)

    def _ei_ap_info(self):
        return {'name': _("Cash voucher %s", self.name), 'partner': self.partner_id, 'amount': self.amount,
                'currency': self.currency_id if 'currency_id' in self._fields else self.journal_id.currency_id or self.company_id.currency_id}

    def _ei_ap_fingerprint_values(self):
        return {k: (self[k].id if hasattr(self[k], 'id') and not isinstance(self[k], (int, float, str)) else self[k])
                for k in ('journal_id', 'date', 'kind', 'amount', 'category_id', 'target_journal_id', 'partner_id', 'description') if k in self._fields}

    def _ei_ap_detail(self):
        sel = dict(self._fields['kind']._description_selection(self.env))
        return {'head': [[_("Voucher"), self.name], [_("Kind"), sel.get(self.kind, '')], [_("Cash box"), self.journal_id.display_name or ''],
                         [_("Date"), str(self.date or '')], [_("Category"), self.category_id.display_name or ''],
                         [_("Party"), self.partner_id.display_name or ''], [_("Description"), self.description or ''],
                         [_("Transfer to"), self.target_journal_id.display_name or '']],
                'columns': [], 'rows': [], 'totals': [[_("Amount"), self._ei_ap_money(self.amount)]]}

    def action_submit(self):
        res = super().action_submit()
        for r in self.filtered(lambda x: x.state == 'submitted' and x._approval_required()):
            self.env['ei.approval.request']._submit(r)
        return res

    def _ei_ap_do_submit(self):
        return self.action_submit()

    def action_approve(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_approve()
        return self._ei_ap_route_approve()

    def _ei_ap_do_approve(self):
        return self.action_approve()

    def _ei_ap_after_approved(self):
        return _("Posted to the cash book.") if self.state == 'posted' else False

    def _ei_ap_do_return(self, reason):
        self.write({'state': 'draft'})

    def _ei_ap_do_reject(self, reason):
        super(EiCashVoucher, self).action_reject(reason=reason)

    def action_reject(self, reason=None):
        """A voucher waiting in an approval request is rejected through the request (the reason and the timeline stay together)."""
        if self.env.context.get('ei_ap_deciding'):
            return super().action_reject(reason=reason)
        Req = self.env['ei.approval.request']
        for r in self:
            req = Req._pending_for(r)
            if req:
                req.action_reject(reason)
            else:
                super(EiCashVoucher, r).action_reject(reason=reason)
        return True


class EiLifting(models.Model):
    _name = 'ei.lifting'
    _inherit = ['ei.lifting', 'ei.approval.mixin']
    _ei_ap_flow = 'lifting'
    _ei_ap_group = 'ei_material_lifting.group_ei_lifting_reviewer'
    _ei_ap_waiting = ('draft',)

    def _ei_ap_info(self):
        cur = self.da_line_id.currency_id or self.company_id.currency_id
        return {'name': _("Truck loading %s", self.display_name), 'partner': self.customer_id,
                'amount': (self.claimed_mtl or 0.0) * (self.da_line_id.sale_rate or 0.0), 'currency': cur}

    def _ei_ap_fingerprint_values(self):
        return {k: (self[k].id if isinstance(self._fields[k], fields.Many2one) else self[k])
                for k in ('da_line_id', 'vehicle_no', 'gate_pass_no', 'weighbridge_no', 'claimed_mtl', 'weighed_mtl', 'gross_kg', 'tare_kg', 'date')
                if k in self._fields}

    def _ei_ap_detail(self):
        g = lambda n: self[n] if n in self._fields else False
        return {'head': [[_("Loading"), self.display_name], [_("DA"), self.da_id.name or ''], [_("Customer"), self.customer_id.display_name or ''],
                         [_("Material"), self.product_id.display_name or ''], [_("Truck"), g('vehicle_no') or ''], [_("Gate pass"), g('gate_pass_no') or ''],
                         [_("Weighbridge slip"), g('weighbridge_no') or ''], [_("Date"), str(g('date') or '')]],
                'columns': [], 'rows': [],
                'totals': [[_("Claimed MTL"), f"{g('claimed_mtl') or 0:,.3f}"], [_("Weighed MTL"), f"{g('weighed_mtl') or 0:,.3f}"],
                           [_("Difference MTL"), f"{g('discrepancy_mtl') or 0:,.3f}"]]}

    def _ei_ap_do_submit(self):
        return self.env['ei.approval.request']._submit(self)

    def action_verify(self):
        if self.env.context.get('ei_ap_deciding'):
            return super().action_verify()
        return self._ei_ap_route_approve()

    def _ei_ap_do_approve(self):
        return self.action_verify()

    def _ei_ap_after_approved(self):
        return _("The loading counts as lifted: it can be invoiced.") if self.state == 'verified' else False

    def _ei_ap_do_return(self, reason):
        return True

    def _ei_ap_do_reject(self, reason):
        self.action_cancel(reason=_("Rejected at approval: %s", reason))

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('ei_ap_deciding') and set(vals) & {'da_line_id', 'claimed_mtl', 'weighed_mtl', 'gross_kg', 'tare_kg', 'gate_pass_no', 'vehicle_no'}:
            Req = self.env['ei.approval.request']
            for r in self:
                req = Req._pending_for(r)
                if req and Req._fingerprint(r) != req.fingerprint:
                    req._supersede(_("The loading was changed after submission."))
        return res


class EiFeedingDesk(models.AbstractModel):
    _inherit = 'ei.feeding.desk'

    @api.model
    def da_load(self, da_id):
        """The desk shows who checks the DA, and why it came back."""
        res = super().da_load(da_id)
        d = self.env['ei.da'].browse(int(da_id))
        req = self.env['ei.approval.request'].sudo()._latest_for(d)
        res['approval'] = req and {
            'request_id': req.id, 'state': req.state, 'approver': req.approver_id.name or '', 'needs_assignment': req.needs_assignment,
            'note': req.decision_note or '', 'decided_by': req.decided_by.name or ''} or False
        return res
