from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ei')
class TestLifting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.dispatch = mk('l_disp', 'ei_material_lifting.group_ei_dispatch_officer')
        cls.reviewer = mk('l_rev', 'ei_material_lifting.group_ei_lifting_reviewer', 'ei_contract_da.group_ei_contract_approver',
                          'ei_daily_orders.group_ei_order_approver')
        cls.parent = cls.env['res.partner'].create({'name': 'Parent Mill'})
        cls.cust = cls.env['res.partner'].create({'name': 'Cust'})
        cls.prod = cls.env['product.product'].create({'name': 'HR Coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        c = cls.env['ei.contract'].create({'parent_partner_id': cls.parent.id, 'contract_ref': 'C1', 'line_ids': [Command.create({
            'product_id': cls.prod.id, 'ordered_mtl': 100, 'purchase_rate': 200000, 'sale_rate': 210000})]})
        cls.env['ir.attachment'].create({'name': 'c', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        c.action_review(); c.with_user(cls.reviewer).action_approve(); c.action_activate()
        cls.contract = c
        cls.da = cls.mkda('DA-1', 10)
        cls.order = cls.env['ei.daily.order'].generate_from_da(cls.da)
        cls.order.with_user(cls.reviewer).action_approve()
        cls.n = 0

    @classmethod
    def mkda(cls, name, mtl):
        d = cls.env['ei.da'].create({'name': name, 'parent_partner_id': cls.parent.id, 'contract_id': cls.contract.id,
                                     'line_ids': [Command.create({'contract_line_id': cls.contract.line_ids.id, 'mtl': mtl,
                                                                  'customer_id': cls.cust.id})]})
        cls.env['ir.attachment'].create({'name': 'd', 'res_model': 'ei.da', 'res_id': d.id, 'raw': b'x'})
        d.action_review(); d.with_user(cls.reviewer).action_approve()
        return d

    def classify(self, value='direct_dispatch'):
        self.contract.line_ids.with_user(self.reviewer).action_set_ownership(value, 'confirmed by finance')

    def lift(self, mtl=None, da=None, **kw):
        type(self).n += 1
        vals = {'da_line_id': (da or self.da).line_ids.id, 'vehicle_no': 'TRK-%s' % self.n,
                'gate_pass_no': 'GP-%s' % self.n, **kw}
        if mtl is not None:
            vals['claimed_mtl'] = mtl
        l = self.env['ei.lifting'].with_user(self.dispatch).create(vals)
        self.env['ir.attachment'].create({'name': 'gp.jpg', 'res_model': 'ei.lifting', 'res_id': l.id, 'raw': b'x'})
        return l

    # T07
    def test_01_partial_lifting_and_invoice_is_not_lifting(self):
        self.classify()
        ol = self.order.line_ids
        ol.invoice_ref = 'SUP-INV-77'       # supplier invoice arrives early
        self.assertEqual((ol.lifted_mtl, ol.remaining_mtl), (0, 10))
        self.assertEqual(self.da.lifted_mtl, 0)
        l = self.lift(4)
        l.with_user(self.reviewer).action_verify()
        self.assertEqual((l.state, l.verified_mtl), ('verified', 4))
        self.assertEqual((ol.lifted_mtl, ol.remaining_mtl), (4, 6))
        self.assertEqual((self.da.lifted_mtl, self.da.remaining_to_lift, self.da.state), (4, 6, 'approved'))
        self.assertEqual(self.contract.line_ids.lifted_mtl, 4)

    def test_01b_reverse_through_the_screen_wizard(self):
        """The "Reverse lifting" button opens a reason wizard; Confirm used to answer 'Action not allowed'."""
        self.classify()
        l = self.lift(4)
        l.with_user(self.reviewer).action_verify()
        wiz = self.env['ei.reason.wizard'].with_user(self.reviewer).with_context(active_ids=l.ids).create(
            {'res_model': 'ei.lifting', 'method': 'action_reverse', 'reason': 'wrong truck'})
        wiz.action_apply()
        self.assertEqual((l.state, l.reverse_reason), ('reversed', 'wrong truck'))
        self.assertEqual(self.da.lifted_mtl, 0, 'a reversed lifting no longer counts as lifted')

    def test_02_draft_lifting_counts_nothing(self):
        self.classify()
        self.lift(4)
        self.assertEqual(self.da.lifted_mtl, 0)

    def test_03_no_over_lifting(self):
        self.classify()
        self.lift(8).with_user(self.reviewer).action_verify()
        with self.assertRaises(UserError):
            self.lift(3).with_user(self.reviewer).action_verify()
        self.lift(2).with_user(self.reviewer).action_verify()
        self.assertEqual((self.da.state, self.da.remaining_to_lift), ('fulfilled', 0))

    def test_04_ownership_required(self):
        with self.assertRaises(UserError):
            self.lift(1).with_user(self.reviewer).action_verify()
        with self.assertRaises(AccessError):
            self.contract.line_ids.with_user(self.dispatch).action_set_ownership('owned', 'x')

    def test_05_evidence_and_maker_checker(self):
        self.classify()
        l = self.env['ei.lifting'].with_user(self.dispatch).create({
            'da_line_id': self.da.line_ids.id, 'vehicle_no': 'T', 'gate_pass_no': 'GP-NOATT', 'claimed_mtl': 1})
        with self.assertRaises(UserError):
            l.with_user(self.reviewer).action_verify()  # no proof attached
        self.env['ir.attachment'].create({'name': 'x', 'res_model': 'ei.lifting', 'res_id': l.id, 'raw': b'x'})
        with self.assertRaises(AccessError):
            l.with_user(self.dispatch).action_verify()
        self.reviewer.group_ids = [Command.link(self.env.ref('ei_material_lifting.group_ei_dispatch_officer').id)]
        mine = self.env['ei.lifting'].with_user(self.reviewer).create({
            'da_line_id': self.da.line_ids.id, 'vehicle_no': 'T', 'gate_pass_no': 'GP-MINE', 'claimed_mtl': 1})
        self.env['ir.attachment'].create({'name': 'x', 'res_model': 'ei.lifting', 'res_id': mine.id, 'raw': b'x'})
        with self.assertRaises(AccessError):
            mine.with_user(self.reviewer).action_verify()

    def test_06_weighbridge_conversion_and_discrepancy(self):
        self.classify('consignment')
        l = self.lift(5, gross_kg=25000, tare_kg=20100, weighbridge_no='WB-1')
        self.assertEqual((l.net_kg, l.weighed_mtl), (4900, 4.9))
        self.assertAlmostEqual(l.discrepancy_mtl, -0.1)
        with self.assertRaises(UserError):
            l.with_user(self.reviewer).action_verify()   # discrepancy needs a note
        l.discrepancy_note = 'scale vs paper, customer accepted 4.9'
        l.with_user(self.reviewer).action_verify()
        self.assertEqual(l.verified_mtl, 4.9)              # the weighbridge is the verified quantity
        l2 = self.lift(gross_kg=2000, tare_kg=1000)
        with self.assertRaises(UserError):
            l2.with_user(self.reviewer).action_verify()   # weights without a ticket number

    def test_07_tolerance_parameter(self):
        self.classify()
        self.env['ir.config_parameter'].sudo().set_float('ei_material_lifting.tolerance_mtl', 0.2)
        l = self.lift(5, gross_kg=25000, tare_kg=20100, weighbridge_no='WB-2')
        l.with_user(self.reviewer).action_verify()
        self.assertEqual(l.verified_mtl, 4.9)

    def test_08_reversal(self):
        self.classify()
        l = self.lift(10)
        l.with_user(self.reviewer).action_verify()
        self.assertEqual(self.da.state, 'fulfilled')
        with self.assertRaises(UserError):
            l.with_user(self.reviewer).action_reverse('')
        with self.assertRaises(UserError):
            l.with_user(self.reviewer).write({'claimed_mtl': 1})
        l.with_user(self.reviewer).action_reverse('wrong truck')
        self.assertEqual((l.state, self.da.lifted_mtl, self.da.state), ('reversed', 0, 'approved'))
        self.assertEqual(self.contract.state, 'active')

    def test_09_gate_pass_unique_and_delete_rules(self):
        self.classify()
        l = self.lift(1, gate_pass_no='GP-DUP')
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.lift(1, gate_pass_no='GP-DUP')
        l.with_user(self.reviewer).action_verify()
        with self.assertRaises(UserError):
            l.with_user(self.reviewer).unlink()

    def test_10_amendment_keeps_lifting(self):
        self.classify()
        self.lift(4).with_user(self.reviewer).action_verify()
        new = self.env['ei.da'].browse(self.da.action_amend()['res_id'])
        new.line_ids.mtl = 3
        self.env['ir.attachment'].create({'name': 'a', 'res_model': 'ei.da', 'res_id': new.id, 'raw': b'x'})
        new.action_review()
        with self.assertRaises(UserError):
            new.with_user(self.reviewer).action_approve()   # cannot amend below what is lifted
        new.action_cancel('wrong figure')
        new2 = self.env['ei.da'].browse(self.da.action_amend()['res_id'])
        self.assertEqual(new2.amendment_no, 2)
        new2.line_ids.mtl = 12
        self.env['ir.attachment'].create({'name': 'a', 'res_model': 'ei.da', 'res_id': new2.id, 'raw': b'x'})
        new2.action_review()
        new2.with_user(self.reviewer).action_approve()
        self.assertEqual((new2.lifted_mtl, new2.remaining_to_lift, self.da.state), (4, 8, 'amended'))

    def test_11_contract_fulfilment_follows_lifting(self):
        self.classify()
        self.contract.line_ids.with_context(ei_system=True).ordered_mtl = 10
        self.lift(10).with_user(self.reviewer).action_verify()
        self.assertEqual(self.contract.state, 'fulfilled')

    def test_12_ownership_cannot_change_after_lifting(self):
        self.classify('direct_dispatch')
        self.lift(1).with_user(self.reviewer).action_verify()
        with self.assertRaises(UserError):
            self.contract.line_ids.with_user(self.reviewer).action_set_ownership('owned', 'changed mind')
        # no stock moves are ever created by lifting
        self.assertFalse(self.env['stock.move'].search_count([('origin', 'ilike', 'LFT/')]) if 'stock.move' in self.env else False)
