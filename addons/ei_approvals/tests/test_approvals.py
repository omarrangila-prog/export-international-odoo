"""Maker-checker (client requirement, 10 Nov 2026). The numbers are the brief's TEST 01..24; each test says which.
Synthetic people and data only. 'senior_a' and 'senior_b' stand for the two senior people of the brief (TEST 15 / 16): each enters
and each checks the other's entries. They are TEST users, not the client's accounts."""
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'ei')
class TestMakerChecker(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.default_policy = {s['flow']: s['on'] for s in cls.env['ei.approval.policy'].summary()}
        cls.env['ei.approval.policy'].sudo().set_all(True)
        co = cls.env.company
        cls.pkr = cls.env.ref('base.PKR'); cls.pkr.active = True
        g = lambda x: cls.env.ref(x).id
        mk = lambda login, name, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': name, 'login': login, 'company_id': co.id, 'company_ids': [Command.set([co.id])],
            'group_ids': [Command.set([g(x) for x in gs])]})
        staff, appr = 'ei_contract_da.group_ei_contract_staff', 'ei_contract_da.group_ei_contract_approver'
        cls.maker = mk('t_maker', 'TEST Maker', staff)
        cls.checker = mk('t_checker', 'TEST Checker', staff, appr, 'ei_daily_orders.group_ei_order_approver')
        cls.checker2 = mk('t_checker2', 'TEST Checker Two', staff, appr)
        cls.stranger = mk('t_stranger', 'TEST Staff without approval role', staff)
        cls.senior_a = mk('t_senior_a', 'TEST Senior A', staff, appr, 'ei_management_dashboard.group_ei_management')
        cls.senior_b = mk('t_senior_b', 'TEST Senior B', staff, appr, 'ei_management_dashboard.group_ei_management')
        cls.clerk = mk('t_cash', 'TEST Cash clerk', 'ei_cashbook.group_ei_cash_clerk')
        cls.cashier = mk('t_cashier', 'TEST Cash approver', 'ei_cashbook.group_ei_cash_clerk', 'ei_cashbook.group_ei_cash_approver', 'account.group_account_user')
        cls.parent = cls.env['res.partner'].create({'name': 'TEST Mill'})
        cls.cust = cls.env['res.partner'].create({'name': 'TEST Customer'})
        cls.prod = cls.env['product.product'].create({'name': 'TEST coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        cls.R = cls.env['ei.approval.request']
        # an active contract, through maker-checker
        cls.contract = cls.env['ei.contract'].with_user(cls.maker).create({
            'parent_partner_id': cls.parent.id, 'contract_ref': 'T-MC-1', 'currency_id': cls.pkr.id,
            'line_ids': [Command.create({'product_id': cls.prod.id, 'ordered_mtl': 500, 'purchase_rate': 200000, 'sale_rate': 201000})]})
        cls.attach(cls.contract)
        cls.contract.with_user(cls.maker).action_confirm()
        cls.R._pending_for(cls.contract).with_user(cls.checker).action_approve()

    @classmethod
    def attach(cls, rec):
        cls.env['ir.attachment'].sudo().create({'name': 'paper.pdf', 'res_model': rec._name, 'res_id': rec.id, 'raw': b'x'})

    def da(self, name='T-DA', user=None, mtl=10):
        d = self.env['ei.da'].with_user(user or self.maker).create({
            'name': name, 'parent_partner_id': self.parent.id, 'contract_id': self.contract.id,
            'line_ids': [Command.create({'contract_line_id': self.contract.line_ids.id, 'mtl': mtl, 'customer_id': self.cust.id})]})
        self.attach(d)
        return d

    def notices(self, user, kind=None):
        dom = [('user_id', '=', user.id)] + ([('kind', '=', kind)] if kind else [])
        return self.env['ei.approval.notice'].sudo().search(dom)

    # ------------------------------------------------------------------ the default
    def test_00_maker_checker_is_on_after_install_and_the_contract_went_through_it(self):
        self.assertEqual(self.default_policy, {'contract': True, 'da': True, 'order': True, 'cash': True, 'lifting': True})
        self.assertEqual(self.contract.state, 'active')                               # approved -> its next stage
        req = self.R._latest_for(self.contract)
        self.assertEqual((req.state, req.maker_id, req.decided_by), ('approved', self.maker, self.checker))

    # TEST 01-10: create, submit, notify, count, open, review, approve, next stage, maker told, count back down
    def test_01_to_10_the_whole_happy_path(self):
        d = self.da('T-DA-1')
        self.assertEqual((d.state, d.approval_state, d.approval_can_submit), ('draft', 'none', True))         # 01
        before = self.R.with_user(self.checker).counts()['pending_for_me'] + self.R.with_user(self.checker2).counts()['pending_for_me']
        d.with_user(self.maker).action_confirm()                                                                # 02 Submit for Approval
        req = self.R._pending_for(d)
        self.assertEqual((d.state, req.state, req.maker_id), ('under_review', 'pending', self.maker))
        self.assertIn(req.approver_id, self.checker | self.checker2 | self.senior_a | self.senior_b)
        self.assertNotEqual(req.approver_id, self.maker)
        chk = req.approver_id
        self.assertEqual(len(self.notices(chk, 'request').filtered(lambda n: n.request_id == req)), 1)          # 03
        after = self.R.with_user(self.checker).counts()['pending_for_me'] + self.R.with_user(self.checker2).counts()['pending_for_me'] \
            + self.R.with_user(self.senior_a).counts()['pending_for_me'] + self.R.with_user(self.senior_b).counts()['pending_for_me']
        self.assertGreaterEqual(after, before + 1)                                                              # 04
        mine = self.R.with_user(chk).counts()['pending_for_me']
        act = self.R.with_user(chk).open_record_action(req.id)
        self.assertEqual((act['res_model'], act['res_id']), ('ei.da', d.id))                                    # 05
        rv = self.R.with_user(chk).browse(req.id).review_data()
        self.assertEqual((rv['model'], rv['res_id'], len(rv['documents'])), ('ei.da', d.id, 1))                 # 06
        col = {c: i for i, c in enumerate(rv['detail']['columns'])}
        line = rv['detail']['rows'][0]
        self.assertEqual(line[col['MTL']], '10.000')
        self.assertIn('200,000', line[col['Purchase / MTL']]); self.assertIn('201,000', line[col['Sale / MTL']])
        self.assertAlmostEqual(req.amount, 10 * 200000)
        self.assertTrue(rv['row']['can_decide'])
        self.R.with_user(chk).decide(req.id, 'approve', 'Checked against the paper')                           # 07
        self.assertEqual((d.state, req.state, req.decided_by, req.decision_note), ('approved', 'approved', chk, 'Checked against the paper'))  # 08
        self.assertEqual(len(self.notices(self.maker, 'approved').filtered(lambda n: n.request_id == req)), 1)  # 09
        self.assertEqual(self.R.with_user(chk).counts()['pending_for_me'], mine - 1)                          # 10
        kinds = req.event_ids.mapped('kind')
        self.assertTrue({'submitted', 'assigned', 'approved'} <= set(kinds))

    # TEST 11: reject needs a reason; the maker is told
    def test_11_reject_with_a_reason(self):
        d = self.da('T-DA-11'); d.with_user(self.maker).action_confirm()
        req = self.R._pending_for(d); chk = req.approver_id
        with self.assertRaises(UserError):
            self.R.with_user(chk).decide(req.id, 'reject', '  ')
        self.R.with_user(chk).decide(req.id, 'reject', 'Wrong mill on the paper')
        self.assertEqual((d.state, req.state, req.decision_note), ('cancelled', 'rejected', 'Wrong mill on the paper'))
        self.assertTrue(self.notices(self.maker, 'rejected').filtered(lambda n: n.request_id == req))
        self.assertEqual(d.approval_state, 'rejected')

    # TEST 12: returned, corrected, resubmitted as a new round; the history keeps both
    def test_12_return_correct_resubmit(self):
        d = self.da('T-DA-12'); d.with_user(self.maker).action_confirm()
        req = self.R._pending_for(d); chk = req.approver_id
        with self.assertRaises(UserError):
            self.R.with_user(chk).decide(req.id, 'return', '')
        self.R.with_user(chk).decide(req.id, 'return', 'MTL should be 12, see the paper')
        self.assertEqual((d.state, req.state, d.approval_state, d.approval_note), ('draft', 'returned', 'returned', 'MTL should be 12, see the paper'))
        self.assertEqual(self.R.with_user(self.maker).counts()['returned_to_me'], 1)
        d.line_ids.with_user(self.maker).write({'mtl': 12})
        d.with_user(self.maker).action_confirm()
        req2 = self.R._pending_for(d)
        self.assertEqual((req2.round, req2.state), (2, 'pending'))
        self.assertIn('resubmitted', req2.event_ids.mapped('kind'))
        self.assertEqual(len(self.R.with_user(req2.approver_id).browse(req2.id).review_data()['rounds']), 2)
        self.R.with_user(req2.approver_id).decide(req2.id, 'approve')
        self.assertEqual(d.state, 'approved')

    # TEST 13: the maker never approves their own entry, even holding the approver role, through any door
    def test_13_maker_cannot_approve_own(self):
        d = self.da('T-DA-13', user=self.senior_a); d.with_user(self.senior_a).action_confirm()
        req = self.R._pending_for(d)
        self.assertNotEqual(req.approver_id, self.senior_a)
        self.assertNotIn(self.senior_a, req.eligible_user_ids)
        for attempt in (lambda: self.R.with_user(self.senior_a).decide(req.id, 'approve'),
                        lambda: d.with_user(self.senior_a).action_approve(),
                        lambda: self.R.with_user(self.senior_a).decide(req.id, 'return', 'x')):
            with self.assertRaises(AccessError):
                attempt()
        self.assertEqual((d.state, req.state), ('under_review', 'pending'))
        self.assertFalse(self.R.with_user(self.senior_a).browse(req.id).review_data()['row']['can_decide'])

    # TEST 14: someone without the approver role cannot decide someone else's entry
    def test_14_unauthorised_employee(self):
        d = self.da('T-DA-14'); d.with_user(self.maker).action_confirm()
        req = self.R._pending_for(d)
        with self.assertRaises(AccessError):
            self.R.with_user(self.stranger).browse(req.id).action_approve()
        with self.assertRaises(AccessError):
            d.with_user(self.stranger).action_approve()
        with self.assertRaises(AccessError):
            self.R.with_user(self.clerk).decide(req.id, 'approve')          # cannot even read it
        self.assertEqual(req.state, 'pending')

    # TEST 15 / 16: the two senior users : each creates; the other one checks
    def test_15_16_one_senior_creates_the_other_checks_and_back(self):
        d = self.da('T-DA-15', user=self.senior_a); d.with_user(self.senior_a).action_confirm()
        req = self.R._pending_for(d)
        self.assertIn(self.senior_b, req.eligible_user_ids)
        rv = self.R.with_user(self.senior_b).browse(req.id).review_data()                                         # 16
        self.assertTrue(rv['row']['can_decide'])
        self.R.with_user(self.senior_b).decide(req.id, 'approve')
        self.assertEqual((d.state, req.decided_by), ('approved', self.senior_b))
        d2 = self.da('T-DA-15b', user=self.senior_b); d2.with_user(self.senior_b).action_confirm()
        r2 = self.R._pending_for(d2)
        self.R.with_user(self.senior_a).decide(r2.id, 'approve')
        self.assertEqual(r2.decided_by, self.senior_a)

    # TEST 17: two checkers cannot both finalise the same request
    def test_17_no_double_decision(self):
        d = self.da('T-DA-17'); d.with_user(self.maker).action_confirm()
        req = self.R._pending_for(d)
        self.R.with_user(self.checker).decide(req.id, 'approve')
        for u, act in ((self.checker2, 'approve'), (self.checker2, 'reject'), (self.checker, 'approve')):
            with self.assertRaises(UserError):
                self.R.with_user(u).decide(req.id, act, 'late')
        self.assertEqual(len(req.event_ids.filtered(lambda e: e.kind == 'approved')), 1)

    # TEST 18: counts are computed from the records (reloading gives the same), a repeated submit does not notify twice
    def test_18_counts_are_stable_and_notices_unique(self):
        d = self.da('T-DA-18'); d.with_user(self.maker).action_confirm()
        req = self.R._pending_for(d)
        c1 = self.R.with_user(req.approver_id).counts()
        self.assertEqual(self.R._submit(d), req)                                    # submitting again changes nothing
        self.assertEqual(self.R.with_user(req.approver_id).counts(), c1)
        self.assertEqual(len(self.notices(req.approver_id, 'request').filtered(lambda n: n.request_id == req)), 1)
        self.env['ei.approval.notice'].with_user(req.approver_id).mark_read()
        self.assertEqual(self.R.with_user(req.approver_id).counts()['unread'], 0)
        self.assertEqual(self.R.with_user(req.approver_id).counts()['pending_for_me'], c1['pending_for_me'])   # reading is not deciding

    # TEST 19: an approved figure cannot be changed; a change needs an amendment, which is approved again;
    # a document changed while waiting cannot be approved in its old form
    def test_19_reapproval_policy(self):
        d = self.da('T-DA-19'); d.with_user(self.maker).action_confirm()
        self.R._pending_for(d).with_user(self.checker).action_approve()
        with self.assertRaises(UserError):
            d.line_ids.with_user(self.maker).write({'purchase_rate': 1})
        new = self.env['ei.da'].browse(d.with_user(self.maker).action_amend()['res_id'])
        self.assertEqual(new.state, 'draft')
        self.attach(new)
        new.with_user(self.maker).action_confirm()
        r = self.R._pending_for(new)
        self.assertEqual(r.state, 'pending')
        # a truck loading changed while it waits: the old version can no longer be approved
        self.contract.line_ids.with_user(self.checker).action_set_ownership('direct_dispatch', 'test')
        dispatch = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'TEST Dispatch', 'login': 't_dispatch', 'group_ids': [Command.set([self.env.ref('ei_material_lifting.group_ei_dispatch_officer').id])]})
        reviewer = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'TEST Reviewer', 'login': 't_reviewer', 'group_ids': [Command.set([self.env.ref('ei_material_lifting.group_ei_lifting_reviewer').id])]})
        lift = self.env['ei.lifting'].with_user(dispatch).create({'da_line_id': d.line_ids.id, 'vehicle_no': 'T-19', 'gate_pass_no': 'GP-T19', 'claimed_mtl': 4})
        self.attach(lift)
        lift.with_user(dispatch).action_submit_for_approval()
        lr = self.R._pending_for(lift)
        lift.with_user(dispatch).write({'claimed_mtl': 5})
        self.assertEqual(lr.state, 'superseded')
        with self.assertRaises(UserError):
            self.R.with_user(reviewer).browse(lr.id).action_approve()
        with self.assertRaises(UserError):
            lift.with_user(reviewer).action_verify()                         # nor through the old button: it must be resubmitted first
        lift.with_user(dispatch).action_submit_for_approval()
        self.R._pending_for(lift).with_user(reviewer).action_approve()
        self.assertEqual((lift.state, lift.claimed_mtl), ('verified', 5))

    # TEST 21: requests stay inside their company; a checker without access to the company is never chosen
    def test_21_company_boundaries(self):
        other = self.env['res.company'].create({'name': 'TEST Other Co', 'currency_id': self.pkr.id})
        outsider = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'TEST Other company approver', 'login': 't_other', 'company_id': other.id, 'company_ids': [Command.set([other.id])],
            'group_ids': [Command.set([self.env.ref('ei_contract_da.group_ei_contract_approver').id, self.env.ref('ei_contract_da.group_ei_contract_staff').id])]})
        d = self.da('T-DA-21'); d.with_user(self.maker).action_confirm()
        req = self.R._pending_for(d)
        self.assertNotIn(outsider, req.eligible_user_ids)
        self.assertEqual(self.R.with_user(outsider).search_count([('id', '=', req.id)]), 0)
        with self.assertRaises(AccessError):
            self.R.with_user(outsider).decide(req.id, 'approve')

    # TEST 22: a pending cash voucher has no accounting effect; only the checker's approval posts it
    def test_22_pending_money_does_not_post(self):
        cash = self.company_data['default_journal_cash']
        acc = self.company_data['default_account_expense']
        cat = self.env['ei.cash.category'].sudo().create({'name': 'TEST Tea', 'account_id': acc.id})
        moves = self.env['account.move'].sudo().search_count([])
        v = self.env['ei.cash.voucher'].with_user(self.clerk).create({'journal_id': cash.id, 'kind': 'payment', 'amount': 500, 'description': 't', 'category_id': cat.id})
        self.attach(v)
        v.with_user(self.clerk).action_confirm()
        req = self.R._pending_for(v)
        self.assertEqual((v.state, bool(v.move_id), req.approver_id), ('submitted', False, self.cashier))
        self.assertEqual(self.env['account.move'].sudo().search_count([]), moves)
        with self.assertRaises(AccessError):
            v.with_user(self.clerk).action_approve()
        self.R.with_user(self.cashier).decide(req.id, 'approve')
        self.assertEqual((v.state, bool(v.move_id)), ('posted', True))

    # TEST 23: nobody else may check: "Assignment required", administrators told, never self-approved
    def test_23_no_eligible_checker(self):
        lonely = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'TEST Only cash approver', 'login': 't_lonely', 'company_id': self.env.company.id, 'company_ids': [Command.set([self.env.company.id])],
            'group_ids': [Command.set([self.env.ref('ei_cashbook.group_ei_cash_clerk').id, self.env.ref('ei_cashbook.group_ei_cash_approver').id,
                                       self.env.ref('account.group_account_user').id])]})
        # every other cash approver loses the role for this test
        appr = self.env.ref('ei_cashbook.group_ei_cash_approver')
        for u in self.env['res.users'].search([('all_group_ids', 'in', [appr.id])]) - lonely:
            u.sudo().group_ids = [Command.unlink(appr.id)]
        cash = self.company_data['default_journal_cash']
        acc = self.company_data['default_account_expense']
        cat = self.env['ei.cash.category'].sudo().create({'name': 'TEST Fuel', 'account_id': acc.id})
        v = self.env['ei.cash.voucher'].with_user(lonely).create({'journal_id': cash.id, 'kind': 'payment', 'amount': 300, 'description': 'fuel', 'category_id': cat.id})
        self.attach(v)
        v.with_user(lonely).action_confirm()
        req = self.R._pending_for(v)
        self.assertTrue(req.needs_assignment); self.assertFalse(req.approver_id)
        self.assertEqual(v.state, 'submitted')
        admins = self.env['res.users'].search([('all_group_ids', 'in', [self.env.ref('base.group_system').id]), ('id', '!=', 1)])
        self.assertTrue(self.env['ei.approval.notice'].sudo().search([('request_id', '=', req.id), ('kind', '=', 'assignment'), ('user_id', 'in', admins.ids)]))
        with self.assertRaises(AccessError):
            self.R.with_user(lonely).decide(req.id, 'approve')
        self.assertEqual(v.state, 'submitted')
        # an administrator gives the role to someone else and assigns the request
        self.cashier.sudo().group_ids = [Command.link(appr.id)]
        admin = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'TEST Administrator', 'login': 't_admin', 'company_id': self.env.company.id, 'company_ids': [Command.set([self.env.company.id])],
            'group_ids': [Command.set([self.env.ref('base.group_system').id, self.env.ref('ei_legacy_master.group_ei_user').id])]})
        with self.assertRaises(AccessError):
            self.R.with_user(self.clerk).browse(req.id).action_reassign(self.cashier.id)          # not an administrator
        self.R.with_user(admin).browse(req.id).action_reassign(self.cashier.id)
        self.assertEqual((req.approver_id, req.needs_assignment), (self.cashier, False))
        self.R.with_user(self.cashier).decide(req.id, 'approve')
        self.assertEqual(v.state, 'posted')

    # the approval rule can name the checkers; the role still applies, and the maker is still excluded
    def test_rule_named_checker_and_threshold(self):
        rule = self.env.ref('ei_approvals.rule_da')
        rule.sudo().approver_user_ids = [Command.set([self.senior_b.id, self.senior_a.id])]
        d = self.da('T-DA-R1'); d.with_user(self.maker).action_confirm()
        self.assertEqual(self.R._pending_for(d).eligible_user_ids, self.senior_b | self.senior_a)
        big = self.env['ei.approval.rule'].sudo().create({'name': 'Big DAs: Senior A only', 'flow': 'da', 'min_amount': 5000000,
                                                           'approver_group_id': self.env.ref('ei_contract_da.group_ei_contract_approver').id,
                                                           'approver_user_ids': [Command.set([self.senior_a.id])]})
        d2 = self.da('T-DA-R2', mtl=30); d2.with_user(self.maker).action_confirm()           # 30 x 200,000 = 6,000,000
        r2 = self.R._pending_for(d2)
        self.assertEqual((r2.rule_id, r2.approver_id), (big, self.senior_a))
        with self.assertRaises(AccessError):
            self.R.with_user(self.senior_b).decide(r2.id, 'approve')                             # not a checker under that rule
        with self.assertRaises(AccessError):
            self.env['ei.approval.rule'].with_user(self.senior_a).create({'name': 'x', 'flow': 'da'})   # only administrators change rules

    # overdue requests are marked once and management is told once
    def test_overdue_escalates_once(self):
        d = self.da('T-DA-O'); d.with_user(self.maker).action_confirm()
        req = self.R._pending_for(d)
        req.sudo().due_at = fields.Datetime.now() - timedelta(hours=1)
        self.assertTrue(req.is_overdue)
        self.R._cron_escalate(); self.R._cron_escalate()
        self.assertEqual((req.urgent, req.priority), (True, 'urgent'))
        self.assertEqual(len(req.event_ids.filtered(lambda e: e.kind == 'escalated')), 1)
        self.assertEqual(len(self.notices(self.senior_a, 'escalated').filtered(lambda n: n.request_id == req)), 1)
        self.assertGreaterEqual(self.R.with_user(req.approver_id).counts()['overdue_for_me'], 1)

    # the timeline cannot be rewritten; a maker sees their own requests, not other people's
    def test_audit_trail_and_visibility(self):
        d = self.da('T-DA-A'); d.with_user(self.maker).action_confirm()
        req = self.R._pending_for(d)
        ev = req.event_ids[:1]
        with self.assertRaises(AccessError):
            ev.write({'note': 'changed'})
        with self.assertRaises(AccessError):
            ev.unlink()
        with self.assertRaises(AccessError):
            req.with_user(self.maker).write({'state': 'approved'})
        self.assertEqual(self.R.with_user(self.stranger).search_count([('id', '=', req.id)]), 0)
        self.assertEqual(self.R.with_user(self.maker).search_count([('id', '=', req.id)]), 1)
        data = self.R.with_user(req.approver_id).center_data(tab='pending')
        self.assertIn(req.id, [r['id'] for r in data['rows']])
        self.assertEqual(data['tabs']['pending'], data['counts']['pending_for_me'])

    # the second-person steps of other modules come into the same centre: the daily cash count as the example
    def test_queue_cash_count_through_the_centre(self):
        cash = self.company_data['default_journal_cash']
        count = self.env['ei.cash.count'].with_user(self.clerk).create({'journal_id': cash.id, 'counted_amount': 0})
        self.R._queue_sync(force=True)
        req = self.R._pending_for(count)
        self.assertEqual((req.flow, req.maker_id, req.approver_id), ('cashcount', self.clerk, self.cashier))
        self.assertTrue(self.notices(self.cashier, 'request').filtered(lambda n: n.request_id == req))
        self.assertFalse(self.R.with_user(self.cashier).browse(req.id)._row()['can_reject'])          # a count is corrected, not rejected
        with self.assertRaises(AccessError):
            self.R.with_user(self.clerk).decide(req.id, 'approve')                                    # the counter never closes their own count
        self.R.with_user(self.cashier).decide(req.id, 'return', 'Count the coins again')
        self.R._queue_sync(force=True)
        self.assertFalse(self.R._pending_for(count))                                                  # not reopened until the count changes
        count.with_user(self.clerk).write({'counted_amount': 0.0, 'discrepancy_note': 'recounted'})
        self.env.flush_all()                                  # the correction is saved later than the return (a later day, in real use)
        self.env.cr.execute("UPDATE ei_cash_count SET write_date = now() + interval '1 hour' WHERE id = %s", [count.id])
        count.invalidate_recordset()
        self.R._queue_sync(force=True)
        req2 = self.R._pending_for(count)
        self.assertEqual(req2.round, 2)
        self.R.with_user(self.cashier).decide(req2.id, 'approve', 'Checked')
        self.assertEqual((count.state, req2.state, req2.decided_by), ('closed', 'approved', self.cashier))

    def test_queue_decided_on_the_document_closes_the_request(self):
        cash = self.company_data['default_journal_cash']
        count = self.env['ei.cash.count'].with_user(self.clerk).create({'journal_id': cash.id, 'counted_amount': 0, 'date': fields.Date.today() - timedelta(days=3)})
        self.R._queue_sync(force=True)
        req = self.R._pending_for(count)
        count.with_user(self.cashier).action_close()                                                 # the old button on the count itself
        self.assertEqual((count.state, req.state, req.decided_by), ('closed', 'approved', self.cashier))
        self.assertIn('approved', req.event_ids.mapped('kind'))
        other = self.env['ei.cash.count'].with_user(self.clerk).create({'journal_id': cash.id, 'counted_amount': 0, 'date': fields.Date.today() - timedelta(days=4)})
        with self.assertRaises(AccessError):
            other.with_user(self.clerk).action_close()                                                # never the person who counted
