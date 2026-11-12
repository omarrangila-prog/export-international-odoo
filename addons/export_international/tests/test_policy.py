"""Approval switched OFF by an administrator (the 9 Nov 2026 decision, superseded on 10 Nov 2026 by maker-checker ON by default; see
ei_approvals/tests). With approval off the person entering a record confirms it, and security (rights, posting rights, checks) still
applies. New entries in PKR or USD only. Synthetic data only."""
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'ei')
class TestPolicy(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ei.approval.policy'].sudo().set_all(False)          # an administrator switched routine approval off
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': cls.env.company.id, 'company_ids': [Command.set([cls.env.company.id])],
            'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.op = mk('p_op', 'ei_contract_da.group_ei_contract_staff', 'ei_material_lifting.group_ei_dispatch_officer')
        cls.checker = mk('p_chk', 'ei_contract_da.group_ei_contract_approver', 'ei_daily_orders.group_ei_order_approver',
                         'ei_material_lifting.group_ei_lifting_reviewer')
        cls.clerk = mk('p_clerk', 'ei_cashbook.group_ei_cash_clerk')
        cls.cashier = mk('p_cashier', 'ei_cashbook.group_ei_cash_clerk', 'account.group_account_user')
        cls.parent = cls.env['res.partner'].create({'name': 'Synthetic Mill'})
        cls.cust = cls.env['res.partner'].create({'name': 'Synthetic Customer'})
        cls.prod = cls.env['product.product'].create({'name': 'HR coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        cls.pkr = cls.env.ref('base.PKR'); cls.pkr.active = True
        cls.usd = cls.env.ref('base.USD'); cls.usd.active = True

    def attach(self, rec):
        self.env['ir.attachment'].sudo().create({'name': 'paper.pdf', 'res_model': rec._name, 'res_id': rec.id, 'raw': b'x'})

    def contract(self, ref='P-1', **kw):
        c = self.env['ei.contract'].with_user(self.op).create({
            'parent_partner_id': self.parent.id, 'contract_ref': ref, 'currency_id': self.pkr.id, **kw,
            'line_ids': [Command.create({'product_id': self.prod.id, 'ordered_mtl': 50, 'purchase_rate': 200000, 'sale_rate': 201000})]})
        self.attach(c)
        return c

    def da(self, c, name='P-DA-1', **kw):
        d = self.env['ei.da'].with_user(self.op).create({
            'name': name, 'parent_partner_id': self.parent.id, 'contract_id': c.id, **kw,
            'line_ids': [Command.create({'contract_line_id': c.line_ids.id, 'mtl': 10, 'customer_id': self.cust.id})]})
        self.attach(d)
        return d

    # AP-01
    def test_ap01_an_administrator_can_switch_routine_approval_off(self):
        self.assertEqual({s['flow']: s['on'] for s in self.env['ei.approval.policy'].summary()},
                         {'contract': False, 'da': False, 'order': False, 'cash': False, 'lifting': False, 'daybook': False})

    # AP-02: one click by the person entering the record, through contract -> DA -> daily order -> truck loading
    def test_ap02_the_person_entering_confirms_with_one_click(self):
        c = self.contract()
        c.with_user(self.op).action_confirm()
        self.assertEqual(c.state, 'active')
        d = self.da(c)
        d.with_user(self.op).action_confirm()
        self.assertEqual((d.state, d.approved_by), ('approved', self.op))
        order = self.env['ei.daily.order'].with_user(self.op).generate_from_da(d)
        order.sudo().action_confirm()              # an operator of the orders module would do the same; the rule is the policy
        self.assertEqual(order.state, 'approved')
        c.line_ids.with_user(self.checker).action_set_ownership('direct_dispatch', 'synthetic')
        lift = self.env['ei.lifting'].with_user(self.op).create({'da_line_id': d.line_ids.id, 'vehicle_no': 'T-1', 'gate_pass_no': 'GP-P1', 'claimed_mtl': 4})
        self.attach(lift)
        ev = self.env['ei.approval.evidence'].with_user(self.op).get_evidence('ei.lifting', lift.id, 'action_verify')
        self.assertEqual((ev['blocked'], ev['you']['direct']), ('', True))   # the confirmation box lets the maker confirm, too
        lift.with_user(self.op).action_verify()     # verified by the person who entered it: policy off
        self.assertEqual(lift.state, 'verified')

    # AP-03: "Send for review" on one record, and the policy switched on for a workflow
    def test_ap03_send_for_review_routes_to_a_second_person(self):
        c = self.contract('P-2')
        c.with_user(self.op).action_confirm()
        d = self.da(c, review_requested=True)
        d.with_user(self.op).action_confirm()
        self.assertEqual(d.state, 'under_review')                  # waits for the reviewer
        with self.assertRaises(AccessError):
            d.with_user(self.op).action_approve()                  # not by the maker, not without the approver right
        d.with_user(self.checker).action_approve()
        self.assertEqual(d.state, 'approved')
        self.env['ir.config_parameter'].sudo().set_bool('ei_approval.contract', True)
        c2 = self.contract('P-3')
        c2.with_user(self.op).action_confirm()
        self.assertEqual(c2.state, 'reviewed')
        self.env['ir.config_parameter'].sudo().set_bool('ei_approval.contract', False)     # OFF again
        c2.with_user(self.op).action_confirm()
        self.assertEqual(c2.state, 'active')

    # AP-04: approval off never grants posting rights or skips checks
    def test_ap04_security_and_checks_stay_on(self):
        cash = self.company_data['default_journal_cash']
        cat = self.env['ei.cash.category'].sudo().create({'name': 'Tea', 'account_id': self.company_data['default_account_expense'].id})
        v = self.env['ei.cash.voucher'].with_user(self.clerk).create({'journal_id': cash.id, 'kind': 'payment', 'amount': 500,
                                                                     'description': 'tea', 'category_id': cat.id})
        self.attach(v)
        v.with_user(self.clerk).action_confirm()
        self.assertEqual((v.state, v.move_id), ('submitted', self.env['account.move']))    # no accounting rights: not posted
        with self.assertRaises(AccessError):
            v.with_user(self.clerk).action_approve()
        v2 = self.env['ei.cash.voucher'].with_user(self.cashier).create({'journal_id': cash.id, 'kind': 'payment', 'amount': 500,
                                                                         'description': 'tea', 'category_id': cat.id})
        self.attach(v2)
        v2.with_user(self.cashier).action_confirm()
        self.assertEqual(v2.state, 'posted')
        self.assertEqual(v2.move_id.state, 'posted')
        # the checks still run: a DA without its paper cannot be confirmed, a DA above the contract cannot be confirmed
        c = self.contract('P-4'); c.with_user(self.op).action_confirm()
        d = self.env['ei.da'].with_user(self.op).create({'name': 'P-DA-NOPAPER', 'parent_partner_id': self.parent.id, 'contract_id': c.id,
                                                          'line_ids': [Command.create({'contract_line_id': c.line_ids.id, 'mtl': 10})]})
        with self.assertRaises(UserError):
            d.with_user(self.op).action_confirm()
        big = self.da(c, 'P-DA-BIG'); big.line_ids.mtl = 500
        with self.assertRaises(UserError):
            big.with_user(self.op).action_confirm()

    # AP-05
    def test_ap05_only_an_administrator_changes_the_policy(self):
        with self.assertRaises(UserError):
            self.env['ei.approval.policy'].with_user(self.op).set_all(True)
        with self.assertRaises(AccessError):
            self.env['res.config.settings'].with_user(self.op).create({'ei_approval_da': True}).execute()
        self.assertFalse(self.env['ei.approval.policy'].flow_on('da'))

    # CFG-01..04
    def test_cfg_new_entries_in_pkr_only_old_ones_untouched(self):
        self.assertEqual(self.contract('P-5').currency_id, self.pkr)
        with self.assertRaises(UserError):                         # PKR only since 11 Nov 2026: USD is refused like any other
            self.env['ei.contract'].with_user(self.op).create({'parent_partner_id': self.parent.id, 'contract_ref': 'P-6', 'currency_id': self.usd.id})
        eur = self.env.ref('base.EUR'); eur.active = True
        with self.assertRaises(UserError):
            self.env['ei.contract'].with_user(self.op).create({'parent_partner_id': self.parent.id, 'contract_ref': 'P-7', 'currency_id': eur.id})
        old = self.env['ei.contract'].sudo().create({'parent_partner_id': self.parent.id, 'contract_ref': 'P-OLD', 'currency_id': self.pkr.id})
        self.env.cr.execute("UPDATE ei_contract SET currency_id = %s WHERE id = %s", (eur.id, old.id))   # an old record in EUR
        old.invalidate_recordset()
        old.notes = 'kept'                                         # editing other fields of an old record still works
        self.assertEqual((old.currency_id, old.notes), (eur, 'kept'))
        self.assertEqual(self.env['ei.contract']._fields['currency_id'].domain, "[('name', '=', 'PKR')]")

    def test_cash_count_shows_the_book_side_while_counting(self):
        cash = self.company_data['default_journal_cash']
        cat = self.env['ei.cash.category'].sudo().create({'name': 'Tea', 'account_id': self.company_data['default_account_expense'].id})
        v = self.env['ei.cash.voucher'].with_user(self.cashier).create({'journal_id': cash.id, 'kind': 'payment', 'amount': 500,
                                                                        'description': 'tea', 'category_id': cat.id})
        self.attach(v)
        v.with_user(self.cashier).action_confirm()
        c = self.env['ei.cash.count'].with_user(self.cashier).create({'journal_id': cash.id, 'counted_amount': 1000})
        self.assertEqual(c.counted_amount, 1000)                             # a typed total is kept (no notes listed)
        self.assertEqual((c.now_payments, c.now_book), (500, -500))          # the book side is live before the day is closed
        self.assertEqual(c.now_difference, 1500)
        self.assertIn(cash.name, c.display_name)

    def test_rates_every_line_carries_a_purchase_and_a_sale_rate(self):
        """Client question, 9 Nov 2026: do all entries have a sale rate and a purchase rate? Yes: nothing goes forward without both."""
        from odoo.addons.ei_da_feeding.models import feeding_engine as fe
        for kw in ({'purchase_rate': '0', 'sale_rate': '230500'}, {'purchase_rate': '229500', 'sale_rate': '0'},
                   {'purchase_rate': '-5', 'sale_rate': '230500'}):
            with self.assertRaises(fe.FeedingError):
                fe.feed('direct_no_commission', 4, **kw)
        bad = self.env['ei.contract'].with_user(self.op).create({
            'parent_partner_id': self.parent.id, 'contract_ref': 'P-R0', 'currency_id': self.pkr.id,
            'line_ids': [Command.create({'product_id': self.prod.id, 'ordered_mtl': 50, 'purchase_rate': 200000})]})   # no sale rate
        self.attach(bad)
        with self.assertRaises(UserError):
            bad.with_user(self.op).action_confirm()
        c = self.contract('P-R1')
        c.with_user(self.op).action_confirm()
        d = self.da(c, 'P-DA-R')
        d.line_ids.sale_rate = 0                                    # a DA line typed to zero on the plain form
        with self.assertRaises(UserError):
            d.with_user(self.op).action_confirm()
        self.assertEqual(d.state, 'draft')
        d.line_ids.sale_rate = 201000
        d.with_user(self.op).action_confirm()
        self.assertEqual(d.state, 'approved')
