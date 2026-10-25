from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ei')
class TestOrders(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.maker = mk('o_maker', 'ei_contract_da.group_ei_contract_staff')
        cls.checker = mk('o_chk', 'ei_contract_da.group_ei_contract_approver', 'ei_daily_orders.group_ei_order_approver')
        cls.parent = cls.env['res.partner'].create({'name': 'Parent Mill'})
        cls.cust = cls.env['res.partner'].create({'name': 'Cust'})
        cls.prod = cls.env['product.product'].create({'name': 'HR Coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        c = cls.env['ei.contract'].create({
            'parent_partner_id': cls.parent.id, 'contract_ref': 'C1', 'line_ids': [Command.create({
                'product_id': cls.prod.id, 'ordered_mtl': 100, 'purchase_rate': 200000, 'sale_rate': 210000})]})
        cls.env['ir.attachment'].create({'name': 'c', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        c.action_review(); c.with_user(cls.checker).action_approve(); c.action_activate()
        cls.contract = c
        cls.da = cls.env['ei.da'].create({'name': 'DA-1', 'parent_partner_id': cls.parent.id, 'contract_id': c.id,
                                          'line_ids': [Command.create({'contract_line_id': c.line_ids.id, 'mtl': 10,
                                                                       'customer_id': cls.cust.id})]})
        cls.env['ir.attachment'].create({'name': 'd', 'res_model': 'ei.da', 'res_id': cls.da.id, 'raw': b'x'})
        cls.da.action_review(); cls.da.with_user(cls.checker).action_approve()
        cls.Order = cls.env['ei.daily.order']

    def test_01_generate_is_idempotent(self):
        o1 = self.Order.generate_from_da(self.da)
        o2 = self.Order.generate_from_da(self.da)
        self.assertEqual(o1, o2)
        self.assertEqual((len(o1.line_ids), o1.line_ids.requested_mtl, o1.state), (1, 10, 'draft'))
        self.assertEqual(self.Order.search_count([('parent_partner_id', '=', self.parent.id)]), 1)
        self.assertTrue(o1.name.startswith('DOR/'))

    def test_02_unapproved_da_does_not_generate(self):
        d = self.env['ei.da'].create({'name': 'DA-D', 'parent_partner_id': self.parent.id, 'contract_id': self.contract.id})
        with self.assertRaises(UserError):
            self.Order.generate_from_da(d)

    def test_03_no_invoice_is_created_and_quantity_is_capped(self):
        moves = self.env['account.move'].search_count([])
        o = self.Order.generate_from_da(self.da)
        o.with_user(self.checker).action_approve()
        self.assertEqual(self.env['account.move'].search_count([]), moves)  # no premature invoice
        o.line_ids.with_context(ei_system=True).requested_mtl = 11
        with self.assertRaises(UserError):
            o.with_user(self.checker).action_approve() if o.state == 'draft' else o.line_ids._check_quantity()

    def test_04_approval_rules_and_locking(self):
        o = self.Order.generate_from_da(self.da)
        with self.assertRaises(AccessError):
            o.with_user(self.maker).action_approve()
        o.with_user(self.checker).action_approve()
        self.assertEqual(o.state, 'approved')
        with self.assertRaises(UserError):
            o.line_ids.write({'requested_mtl': 1})
        with self.assertRaises(UserError):
            o.write({'date': '2020-01-01'})
        with self.assertRaises(UserError):
            o.unlink()
        # approved order cannot be regenerated into for the same day
        with self.assertRaises(UserError):
            self.Order.generate_from_da(self.da)

    def test_05_invoice_ref_late_and_cancel(self):
        o = self.Order.generate_from_da(self.da)
        with self.assertRaises(UserError):
            o.line_ids.invoice_ref = 'INV-1'  # not approved yet
        o.with_user(self.checker).action_approve()
        o.line_ids.invoice_ref = 'INV-1'
        self.assertEqual(o.line_ids.lifted_mtl, 0)   # invoice does not mean lifted
        with self.assertRaises(UserError):
            o.action_cancel('x')                      # invoice recorded

    def test_05b_cancel_through_the_screen_wizard(self):
        """The "Cancel order request" button opens a reason wizard; Confirm used to answer 'Action not allowed'."""
        o = self.Order.generate_from_da(self.da, '2026-10-02')
        wiz = self.env['ei.reason.wizard'].with_context(active_ids=o.ids).create(
            {'res_model': 'ei.daily.order', 'method': 'action_cancel', 'reason': 'wrong day'})
        wiz.action_apply()
        self.assertEqual(o.state, 'cancelled')
        self.assertEqual(self.da.line_ids._requestable_mtl(), 10)

    def test_06_cancel_frees_quantity(self):
        o = self.Order.generate_from_da(self.da, '2026-10-01')
        o.action_cancel('wrong day')
        self.assertEqual(self.da.line_ids._requestable_mtl(), 10)
        o3 = self.Order.generate_from_da(self.da, '2026-10-05')
        with self.assertRaises(UserError):
            o3.action_cancel('')

    def test_07_partial_requests_across_days(self):
        o = self.Order.generate_from_da(self.da, '2026-10-01')
        o.line_ids.requested_mtl = 4
        o2 = self.Order.generate_from_da(self.da, '2026-10-02')
        self.assertEqual(o2.line_ids.requested_mtl, 6)
        self.assertEqual(self.Order.generate_from_da(self.da, '2026-10-03').line_ids, self.env['ei.daily.order.line'])

    def test_08_report_renders(self):
        o = self.Order.generate_from_da(self.da)
        o.with_user(self.checker).action_approve()
        html = self.env['ir.actions.report'].with_user(self.checker)._render_qweb_html('ei_daily_orders.report_daily_order', o.ids)[0]
        self.assertIn(o.name.encode(), html)
        act = o.with_user(self.checker).action_print()
        self.assertEqual((act['report_name'], o.print_count), ('ei_daily_orders.report_daily_order', 1))
