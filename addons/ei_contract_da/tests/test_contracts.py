from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ei')
class TestContracts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.maker = mk('k_maker', 'ei_contract_da.group_ei_contract_staff')
        cls.checker = mk('k_chk', 'ei_contract_da.group_ei_contract_approver')
        cls.acct = mk('k_acct', 'ei_contract_da.group_ei_formula_approver')
        cls.over = mk('k_over', 'ei_contract_da.group_ei_da_override')
        cls.isl = cls.env['res.partner'].create({'name': 'Parent Steel Ltd'})
        cls.hadeed = cls.env['res.partner'].create({'name': 'Other Parent'})
        cls.cust = cls.env['res.partner'].create({'name': 'Customer X'})
        cls.prod = cls.env['product.product'].create({'name': 'HR Coil 2mm', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        cls.Contract = cls.env['ei.contract'].with_user(cls.maker)
        cls.DA = cls.env['ei.da'].with_user(cls.maker)

    # ---- helpers
    def contract(self, mtl=100, formula=None, ref='ISL-001', **line_kw):
        line = {'product_id': self.prod.id, 'ordered_mtl': mtl, 'purchase_rate': 200000, 'sale_rate': 210000, **line_kw}
        if formula:
            line.update(formula_id=formula.id, basic_rate=210000,
                        param_ids=[Command.create({'key': 'deduction_pct', 'value': '1.32'})])
        c = self.Contract.create({'parent_partner_id': self.isl.id, 'contract_ref': ref,
                                  'line_ids': [Command.create(line)]})
        self.env['ir.attachment'].sudo().create({'name': 'c.pdf', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        return c

    def activate(self, c):
        c.with_user(self.maker).action_review()
        c.with_user(self.checker).action_approve()
        c.with_user(self.maker).action_activate()
        return c

    def da(self, c, mtl, name='DA-1', **kw):
        d = self.DA.create({'name': name, 'parent_partner_id': self.isl.id, 'contract_id': c.id,
                            'line_ids': [Command.create({'contract_line_id': c.line_ids[0].id, 'mtl': mtl,
                                                         'customer_id': self.cust.id, **kw})]})
        self.env['ir.attachment'].sudo().create({'name': 'd.pdf', 'res_model': 'ei.da', 'res_id': d.id, 'raw': b'x'})
        return d

    def approved_formula(self):
        f = self.env.ref('ei_contract_da.formula_example_mill_rate')
        f.with_user(self.acct).action_approve()
        return f

    # ---- formula register
    def test_01_example_formula_is_draft_and_unusable(self):
        f = self.env.ref('ei_contract_da.formula_example_mill_rate')
        self.assertEqual(f.state, 'draft')
        self.assertTrue(all(ok for _t, ok in f.run_tests()))
        c = self.contract(formula=f)
        with self.assertRaises(UserError):
            c.action_review()  # draft formula cannot be used

    def test_02_approval_rules(self):
        f = self.env.ref('ei_contract_da.formula_example_mill_rate')
        with self.assertRaises(AccessError):
            f.with_user(self.maker).action_approve()
        author = self.env['ei.formula.definition'].with_user(self.acct).create({
            'name': 'mine', 'code': 'MINE', 'rationale': 'x', 'rounding_mode': 'final_only',
            'step_ids': [Command.create({'key': 'r', 'kind': 'deduction_pct', 'base_ref': 'basic_rate', 'param': 'p'})]})
        with self.assertRaises(UserError):
            author.action_approve()  # no signed test
        author.write({'test_ids': [Command.create({'name': 't', 'basic_rate': 100, 'params_json': '{"p": "10"}',
                                                   'expected_key': 'r', 'expected_value': '91.00'})]})
        with self.assertRaises(UserError):
            author.action_approve()  # failing test
        author.test_ids.expected_value = '90.00'
        with self.assertRaises(AccessError):
            author.action_approve()  # author cannot approve own formula
        author.with_user(self.env['res.users'].browse(self.acct.id).copy({'login': 'k_acct2'})).action_approve()
        self.assertEqual(author.state, 'approved')

    def test_03_approved_formula_is_immutable_and_versioned(self):
        f = self.approved_formula()
        self.assertEqual(f.state, 'approved')
        for op in (lambda: f.write({'name': 'x'}), lambda: f.step_ids[0].write({'param': 'zz'}),
                   lambda: f.test_ids[0].unlink(), lambda: f.unlink()):
            with self.assertRaises(UserError):
                op()
        res = f.action_new_version()
        v2 = self.env['ei.formula.definition'].browse(res['res_id'])
        self.assertEqual((v2.version, v2.state, v2.supersedes_id), (2, 'draft', f))
        v2.step_ids.param = 'deduction_pct'
        v2.test_ids.expected_value = '207228.00'
        v2.with_user(self.acct).action_approve()
        self.assertEqual((f.state, v2.state), ('retired', 'approved'))

    # ---- T06: frozen at approval
    def test_04_snapshot_frozen_and_visible(self):
        f = self.approved_formula()
        c = self.contract(formula=f)
        line = c.line_ids
        self.assertIn('live preview', line.calc_html)
        self.assertIn('207228.00', line.calc_html)
        self.activate(c)
        self.assertEqual(c.state, 'active')
        self.assertEqual(line.snapshot['values']['mill_rate'], '207228.00')
        self.assertEqual((line.snapshot['formula'], line.snapshot['version']), ('MILL_RATE_DEDUCTION', 1))
        self.assertIn('frozen at approval', line.calc_html)
        # a later formula version never rewrites the approved contract
        v2 = self.env['ei.formula.definition'].browse(f.action_new_version()['res_id'])
        v2.step_ids.write({'param': 'deduction_pct'})
        v2.test_ids.write({'params_json': '{"deduction_pct": "2"}', 'expected_value': '205800.00'})
        v2.with_user(self.acct).action_approve()
        line.invalidate_recordset()
        self.assertEqual(line.snapshot['values']['mill_rate'], '207228.00')
        self.assertEqual(line.snapshot['version'], 1)

    def test_05_gross_spread_on_line(self):
        c = self.contract(mtl=10)
        self.assertEqual((c.line_ids.spread_per_mtl, c.line_ids.expected_gross_spread), (10000, 100000))

    def test_06_missing_parameter_blocks_review(self):
        f = self.approved_formula()
        c = self.contract(formula=f)
        c.line_ids.param_ids.unlink()
        with self.assertRaises(UserError):
            c.action_review()

    # ---- contract workflow
    def test_07_contract_workflow_and_controls(self):
        c = self.contract()
        c.attachment_count
        att = self.env['ir.attachment'].sudo().search([('res_model', '=', 'ei.contract'), ('res_id', '=', c.id)])
        att.unlink()
        with self.assertRaises(UserError):
            c.with_user(self.maker).action_review()  # needs the parent's document
        self.env['ir.attachment'].sudo().create({'name': 'c.pdf', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        c.with_user(self.maker).action_review()
        with self.assertRaises(AccessError):
            c.with_user(self.maker).action_approve()
        self.maker.group_ids = [Command.link(self.env.ref('ei_contract_da.group_ei_contract_approver').id)]
        with self.assertRaises(AccessError):
            c.with_user(self.maker).action_approve()  # maker-checker
        c.with_user(self.checker).action_approve()
        with self.assertRaises(UserError):
            c.with_user(self.checker).write({'contract_ref': 'changed'})
        with self.assertRaises(UserError):
            c.line_ids.with_user(self.checker).write({'sale_rate': 1})
        with self.assertRaises(UserError):
            self.env['ei.contract.line'].with_user(self.checker).create({'contract_id': c.id, 'product_id': self.prod.id, 'ordered_mtl': 1})

    def test_08_duplicate_contract_ref_rejected(self):
        self.contract(ref='DUP')
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.contract(ref='DUP')

    # ---- DA quantity control
    def test_09_da_cannot_exceed_contract_quantity(self):
        c = self.activate(self.contract(mtl=100))
        d1 = self.da(c, 60, 'DA-1')
        d1.action_review(); d1.with_user(self.checker).action_approve()
        self.assertEqual((c.line_ids.allocated_mtl, c.line_ids.remaining_mtl), (60, 40))
        d2 = self.da(c, 50, 'DA-2')
        d2.action_review()
        with self.assertRaises(UserError):
            d2.with_user(self.checker).action_approve()
        d2.line_ids.with_user(self.over).action_authorise_over_quantity('Parent confirmed extra 10 MTL by letter')
        d2.with_user(self.checker).action_approve()
        self.assertEqual(c.line_ids.allocated_mtl, 110)
        self.assertIn('Over-quantity authorised', d2.message_ids.mapped('body')[0] if False else ' '.join(d2.message_ids.mapped('body')))

    def test_10_override_needs_group_and_reason(self):
        c = self.activate(self.contract(mtl=10))
        d = self.da(c, 20)
        with self.assertRaises(AccessError):
            d.line_ids.with_user(self.maker).action_authorise_over_quantity('x')
        with self.assertRaises(UserError):
            d.line_ids.with_user(self.over).action_authorise_over_quantity('')

    def test_11_amendment_frees_old_quantity(self):
        c = self.activate(self.contract(mtl=100))
        d = self.da(c, 80)
        d.action_review(); d.with_user(self.checker).action_approve()
        new = self.env['ei.da'].browse(d.with_user(self.maker).action_amend()['res_id'])
        self.assertEqual((new.amendment_no, new.state, new.previous_id), (1, 'draft', d))
        new.line_ids.mtl = 95
        self.env['ir.attachment'].sudo().create({'name': 'a.pdf', 'res_model': 'ei.da', 'res_id': new.id, 'raw': b'x'})
        new.action_review(); new.with_user(self.checker).action_approve()
        self.assertEqual((d.state, new.state), ('amended', 'approved'))
        self.assertEqual(c.line_ids.allocated_mtl, 95)

    def test_12_da_validations(self):
        c = self.activate(self.contract())
        with self.assertRaises(UserError):  # DA parent differs from contract's
            self.DA.create({'name': 'X', 'parent_partner_id': self.hadeed.id, 'contract_id': c.id})
        d = self.da(c, 10, rate_note=False, sale_rate=215000)
        d.action_review()
        with self.assertRaises(UserError):  # rate differs from contract, no note
            d.with_user(self.checker).action_approve()
        d.line_ids.rate_note = 'Parent price revision letter 12/10'
        d.with_user(self.checker).action_approve()
        d2 = self.da(c, 1, 'DA-OLD')
        d2.date = '2000-01-01'
        c.with_context(ei_system=True).valid_from = '2026-01-01'
        d2.action_review()
        with self.assertRaises(UserError):
            d2.with_user(self.checker).action_approve()  # outside validity

    def test_13_da_maker_checker_and_inactive_contract(self):
        c = self.contract()
        with self.assertRaises(UserError):  # contract not active yet
            d = self.da(c, 5); d.action_review(); d.with_user(self.checker).action_approve()
        self.activate(c)
        d = self.da(c, 5, 'DA-9')
        d.action_review()
        self.checker.group_ids = [Command.link(self.env.ref('ei_contract_da.group_ei_contract_staff').id)]
        mine = self.env['ei.da'].with_user(self.checker).create({'name': 'DA-MINE', 'parent_partner_id': self.isl.id,
                                                                 'contract_id': c.id, 'line_ids': [Command.create({'contract_line_id': c.line_ids.id, 'mtl': 1})]})
        self.env['ir.attachment'].sudo().create({'name': 'd.pdf', 'res_model': 'ei.da', 'res_id': mine.id, 'raw': b'x'})
        mine.action_review()
        with self.assertRaises(AccessError):
            mine.with_user(self.checker).action_approve()

    def test_14_cancel_rules(self):
        c = self.activate(self.contract())
        d = self.da(c, 5)
        with self.assertRaises(UserError):
            d.action_cancel('')
        d.action_cancel('entered twice')
        self.assertEqual(d.state, 'cancelled')
        d2 = self.da(c, 5, 'DA-2'); d2.action_review(); d2.with_user(self.checker).action_approve()
        with self.assertRaises(UserError):
            c.action_cancel('x')  # approved DA exists
        with self.assertRaises(AccessError):
            d2.with_user(self.maker).action_cancel('oops')

    def test_15_contract_revision_supersedes(self):
        c = self.activate(self.contract(mtl=100))
        pending = self.da(c, 10, 'DA-P')
        new = self.env['ei.contract'].browse(c.with_user(self.maker).action_revise()['res_id'])
        self.assertEqual((new.revision, new.state, new.previous_id), (1, 'draft', c))
        self.env['ir.attachment'].sudo().create({'name': 'r.pdf', 'res_model': 'ei.contract', 'res_id': new.id, 'raw': b'x'})
        new.with_user(self.maker).action_review(); new.with_user(self.checker).action_approve()
        self.assertEqual((c.state, new.state, pending.state), ('amended', 'approved', 'cancelled'))
