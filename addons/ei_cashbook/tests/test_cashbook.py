from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'ei')
class TestCashbook(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda login, g: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([cls.env.ref(g).id])]})
        cls.clerk = mk('c_clerk', 'ei_cashbook.group_ei_cash_clerk')
        cls.checker = mk('c_chk', 'ei_cashbook.group_ei_cash_approver')
        cls.cash = cls.company_data['default_journal_cash']
        cls.bank = cls.company_data['default_journal_bank']
        cls.expense = cls.company_data['default_account_expense']
        cls.cat = cls.env['ei.cash.category'].sudo().create({'name': 'Office expenses', 'account_id': cls.expense.id})
        cls.rcat = cls.env['ei.cash.category'].sudo().create({'name': 'Other receipt', 'kind': 'receipt',
                                                              'account_id': cls.company_data['default_account_revenue'].id})
        cls.V = cls.env['ei.cash.voucher']

    def voucher(self, amount=1000, kind='payment', attach=True, **kw):
        v = self.V.with_user(self.clerk).create({
            'journal_id': self.cash.id, 'kind': kind, 'amount': amount, 'description': 'tea and stationery',
            'category_id': (self.rcat if kind == 'receipt' else self.cat).id, **kw})
        if attach:
            self.env['ir.attachment'].sudo().create({'name': 'r.jpg', 'res_model': 'ei.cash.voucher', 'res_id': v.id, 'raw': b'x'})
        return v

    def bal(self):
        return self.cash._ei_ledger_balance('2099-01-01')

    def test_01_receipt_then_payment_posts_cash(self):
        r = self.voucher(5000, 'receipt', attach=False)
        r.action_submit(); r.with_user(self.checker).action_approve()
        p = self.voucher(1200)
        p.action_submit(); p.with_user(self.checker).action_approve()
        self.assertEqual((r.state, p.state), ('posted', 'posted'))
        self.assertEqual(self.bal(), 3800)
        self.assertEqual(p.move_id.state, 'posted')
        self.assertTrue(p.name.startswith('CV/'))

    def test_02_maker_cannot_approve_own_high_risk(self):
        self.clerk.group_ids = [Command.link(self.env.ref('ei_cashbook.group_ei_cash_approver').id)]
        v = self.voucher(1000)
        v.action_submit()
        with self.assertRaises(AccessError):
            v.with_user(self.clerk).action_approve()
        self.cash.ei_self_approve_limit = 1500
        v.with_user(self.clerk).action_approve()
        self.assertEqual(v.state, 'posted')
        big = self.voucher(2000)
        big.action_submit()
        with self.assertRaises(AccessError):
            big.with_user(self.clerk).action_approve()

    def test_03_receipt_attachment_required(self):
        v = self.voucher(1000, attach=False)
        with self.assertRaises(UserError):
            v.action_submit()
        self.cash.ei_receipt_required_over = 5000
        v.action_submit()

    def test_04_posted_voucher_immutable_and_reversal(self):
        v = self.voucher(700)
        v.action_submit(); v.with_user(self.checker).action_approve()
        with self.assertRaises(UserError):
            v.with_user(self.checker).write({'amount': 1})
        with self.assertRaises(UserError):
            v.with_user(self.checker).unlink()
        with self.assertRaises(UserError):
            v.with_user(self.checker).action_reverse('')
        v.with_user(self.checker).action_reverse('wrong amount')
        self.assertEqual((v.state, self.bal()), ('reversed', 0))
        self.assertEqual(v.move_id.state, 'posted')  # original kept, never deleted

    def test_05_reject(self):
        v = self.voucher(10)
        v.action_submit()
        with self.assertRaises(UserError):
            v.with_user(self.checker).action_reject('')
        v.with_user(self.checker).action_reject('no bill')
        self.assertEqual((v.state, v.move_id.id), ('rejected', False))

    def test_06_transfer_to_bank_uses_transfer_account(self):
        r = self.voucher(9000, 'receipt', attach=False); r.action_submit(); r.with_user(self.checker).action_approve()
        t = self.voucher(4000, 'bank_transfer', target_journal_id=self.bank.id, category_id=False)
        t.action_submit()
        self.env.company.transfer_account_id = False
        with self.assertRaises(UserError):
            t.with_user(self.checker).action_approve()
        self.env.company.transfer_account_id = self.company_data['default_account_assets']
        t.with_user(self.checker).action_approve()
        self.assertEqual(self.bal(), 5000)
        self.assertEqual(t.move_id.line_ids.filtered(lambda l: l.debit).account_id, self.company_data['default_account_assets'])

    def test_07_transfer_validation(self):
        t = self.voucher(10, 'bank_transfer', target_journal_id=self.cash.id, category_id=False)
        with self.assertRaises(UserError):
            t.action_submit()
        t2 = self.voucher(10, 'safe_transfer', target_journal_id=self.bank.id, category_id=False)
        with self.assertRaises(UserError):
            t2.action_submit()

    def test_08_category_requires_approved_gl_mapping(self):
        code = self.env['ei.legacy.code'].sudo().create({
            'legacy_code': '8.99', 'source_sheet': 'EXPENSES', 'source_sheet_key': 'EXPENSES', 'source_row': 99,
            'original_name': 'TEST', 'batch_id': self.env['ei.import.batch'].sudo().create({'name': 'x'}).id,
            'proposed_target_type': 'gl_account'})
        with self.assertRaises(UserError):
            self.env['ei.cash.category'].sudo().create({'name': 'x', 'account_id': self.expense.id, 'legacy_code_id': code.id})
        code.with_context(ei_system_write=True).write({'verification_status': 'approved', 'approved_target_type': 'gl_account'})
        cat = self.env['ei.cash.category'].sudo().create({'name': 'x', 'account_id': self.expense.id, 'legacy_code_id': code.id})
        self.assertEqual((code.linked_model, code.linked_res_id), ('account.account', self.expense.id))

    def test_09_cash_count_and_discrepancy(self):
        r = self.voucher(5000, 'receipt', attach=False); r.action_submit(); r.with_user(self.checker).action_approve()
        p = self.voucher(500); p.action_submit(); p.with_user(self.checker).action_approve()
        c = self.env['ei.cash.count'].with_user(self.clerk).create({
            'journal_id': self.cash.id, 'line_ids': [Command.create({'denomination': 1000, 'quantity': 4}),
                                                     Command.create({'denomination': 100, 'quantity': 4})]})
        self.assertEqual(c.counted_amount, 4400)
        with self.assertRaises(AccessError):
            c.with_user(self.clerk).action_close()
        with self.assertRaises(UserError):  # 100 short, no note
            c.with_user(self.checker).action_close()
        c.discrepancy_note = 'one 100 note missing, custodian informed'
        c.with_user(self.checker).action_close()
        self.assertEqual((c.state, c.book_balance, c.discrepancy), ('closed', 4500, -100))
        self.assertEqual((c.receipts, c.payments), (5000, 500))
        self.cash.loss_account_id = False
        with self.assertRaises(UserError):  # no loss account configured
            c.with_user(self.checker).action_post_discrepancy()
        self.cash.loss_account_id = self.company_data['default_account_expense']
        c.with_user(self.checker).action_post_discrepancy()
        self.assertEqual(self.bal(), 4400)
        with self.assertRaises(UserError):
            c.with_user(self.checker).action_post_discrepancy()

    def test_10_custodian_cannot_close_own_count(self):
        self.clerk.group_ids = [Command.link(self.env.ref('ei_cashbook.group_ei_cash_approver').id)]
        c = self.env['ei.cash.count'].with_user(self.clerk).create({'journal_id': self.cash.id, 'counted_amount': 0})
        with self.assertRaises(AccessError):
            c.with_user(self.clerk).action_close()

    def test_11_report_renders(self):
        r = self.voucher(100, 'receipt', attach=False); r.action_submit(); r.with_user(self.checker).action_approve()
        c = self.env['ei.cash.count'].with_user(self.clerk).create({'journal_id': self.cash.id, 'counted_amount': 100})
        c.with_user(self.checker).action_close()
        html = self.env['ir.actions.report'].with_user(self.checker)._render_qweb_html('ei_cashbook.report_cash_count', c.ids)[0]
        self.assertIn(b'Daily Cash Book', html)
        self.assertIn(r.name.encode(), html)
