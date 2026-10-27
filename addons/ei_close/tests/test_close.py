from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'ei')
class TestClose(AccountTestInvoicingCommon):
    """Synthetic figures only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        co = cls.company_data['company']
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': co.id, 'company_ids': [Command.set([co.id])],
            'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.acct = mk('c_acct', 'account.group_account_user')
        cls.mgr = mk('c_mgr', 'account.group_account_manager')
        cls.mgr2 = mk('c_mgr2', 'account.group_account_manager')
        cls.recv = cls.company_data['default_account_receivable']
        cls.income = cls.company_data['default_account_revenue']

    def entry(self, date, amount, partner=None, account=None):
        m = self.env['account.move'].create({'move_type': 'entry', 'date': date, 'line_ids': [
            Command.create({'account_id': (account or self.recv).id, 'partner_id': partner and partner.id, 'debit': max(amount, 0), 'credit': max(-amount, 0), 'name': 'synthetic'}),
            Command.create({'account_id': self.income.id, 'debit': max(-amount, 0), 'credit': max(amount, 0), 'name': 'synthetic'})]})
        m.action_post()
        return m

    def invoice(self, date, amount, post=True):
        inv = self.env['account.move'].create({'move_type': 'out_invoice', 'partner_id': self.partner_a.id, 'invoice_date': date, 'date': date,
                                               'invoice_line_ids': [Command.create({'name': 'coil', 'quantity': 1, 'price_unit': amount, 'tax_ids': [Command.set([])]})]})
        if post:
            inv.action_post()
        return inv

    def sub(self, kind='receivable', date='2026-10-31'):
        c = self.env['ei.subledger.check'].with_user(self.acct).create({'kind': kind, 'date': date})
        c.action_run()
        return c

    # ---------------------------------------------------------------- R3
    def test_01_party_balances_against_the_control_account(self):
        self.invoice('2026-10-05', 1000)
        self.entry('2026-10-06', 200)                                  # on the control account, no party
        self.entry('2026-10-07', -50, partner=self.partner_b)          # typed by hand: a customer in credit
        c = self.sub()
        self.assertEqual((c.control_balance, c.party_total, c.no_party_amount, c.difference), (1150, 950, 200, 200))
        self.assertEqual(c.control_balance, c.party_total + c.no_party_amount)         # every rupee is either a party's or listed
        self.assertEqual((c.manual_count, c.manual_amount), (2, 150))
        self.assertEqual((c.wrong_way_count, c.wrong_way_amount), (1, -50))
        self.assertEqual(sum(c.line_ids.mapped('balance')), 1150)
        self.assertEqual(len(self.env['account.move.line'].search(c.action_open_no_party()['domain'])), 1)
        with self.assertRaises(AccessError):
            c.with_user(self.acct).action_sign()                        # not an accounting manager
        with self.assertRaises(UserError):
            c.with_user(self.mgr).action_sign()                         # listed items need an explanation
        c.with_user(self.acct).note = 'Opening balance typed without a party; credit for Partner B is an advance.'
        c.with_user(self.mgr).action_sign()
        self.assertEqual((c.state, c.signed_by), ('signed', self.mgr))
        with self.assertRaises(UserError):
            c.with_user(self.acct).write({'note': 'changed later'})
        with self.assertRaises(UserError):
            c.action_run()

    def test_02_cut_off_and_payables(self):
        self.invoice('2026-10-05', 1000)
        self.invoice('2026-11-02', 700)                                 # after the date: not counted
        self.assertEqual(self.sub().control_balance, 1000)
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': self.partner_b.id, 'invoice_date': '2026-10-08',
                                                'invoice_line_ids': [Command.create({'name': 'coil', 'quantity': 1, 'price_unit': 400, 'tax_ids': [Command.set([])]})]})
        bill.action_post()
        p = self.sub('payable')
        self.assertEqual((p.control_balance, p.party_total, p.difference, p.manual_count), (400, 400, 0, 0))   # what we owe, shown positive
        with self.assertRaises(AccessError):
            p.with_user(self.acct).action_sign()
        p.with_user(self.mgr).action_sign()                             # clean: no note needed
        self.assertEqual(p.state, 'signed')

    # ---------------------------------------------------------------- close
    def close(self, kind='month', date='2026-10-15', user=None):
        c = self.env['ei.close'].with_user(user or self.acct).create({'kind': kind, 'date': date})
        c.action_refresh()
        return c

    def item(self, c, code):
        return c.item_ids.filtered(lambda i: i.code == code)

    def test_03_month_close_blocks_until_cleared_or_waived_then_locks_the_books(self):
        draft = self.invoice('2026-10-20', 300, post=False)
        c = self.close()
        self.assertEqual((str(c.date_from), str(c.date_to)), ('2026-10-01', '2026-10-31'))
        self.assertEqual(self.item(c, 'draft_moves').status, 'blocker')
        self.assertEqual(self.item(c, 'subledger').status, 'blocker')
        if self.company_data['default_journal_bank']:
            self.assertEqual(self.item(c, 'bank_balance').status, 'blocker')
        with self.assertRaises(UserError):
            c.with_user(self.mgr).action_sign()                         # blockers open
        self.assertEqual(c.state, 'open')
        # the draft is posted, the party balances are signed: those blockers clear themselves on the next check
        draft.action_post()
        for k in ('receivable', 'payable'):
            s = self.sub(k)
            s.with_user(self.acct).note = 'synthetic'
            s.with_user(self.mgr).action_sign()
        c.action_refresh()
        self.assertEqual((self.item(c, 'draft_moves').status, self.item(c, 'subledger').status), ('ok', 'ok'))
        # the rest is waived, one by one, with a reason
        with self.assertRaises(AccessError):
            self.item(c, 'bank_balance').with_user(self.acct).action_waive('no')
        for i in c.item_ids.filtered(lambda i: i.status == 'blocker'):
            with self.assertRaises(UserError):
                i.with_user(self.mgr).action_waive('  ')
            self.env['ei.close.waive.wizard'].with_user(self.mgr).create({'item_id': i.id, 'reason': 'synthetic test company'}).action_waive()
        self.assertEqual(c.n_blockers, 0)
        with self.assertRaises(AccessError):
            self.close(date='2026-09-15', user=self.mgr).with_user(self.mgr).action_sign()    # maker-checker
        c.with_user(self.mgr).action_sign()
        self.assertEqual((c.state, c.signed_by), ('signed', self.mgr))
        self.assertTrue(all('waived_by' in row for row in c.snapshot))
        with self.assertRaises(UserError):
            c.action_refresh()
        c.with_user(self.mgr).action_lock_books()
        self.assertEqual((str(c.books_locked_to), str(c.company_id.fiscalyear_lock_date)), ('2026-10-31', '2026-10-31'))
        late = self.entry('2026-10-25', 10)                             # nobody posts into a closed month: Odoo moves it past the lock
        self.assertGreater(str(late.date), '2026-10-31')

    def test_04_a_waiver_covers_what_was_waived_and_no_more(self):
        self.invoice('2026-10-20', 300, post=False)
        c = self.close()
        i = self.item(c, 'draft_moves')
        i.with_user(self.mgr).action_waive('one draft known, posted tomorrow')
        c.action_refresh()
        self.assertTrue(self.item(c, 'draft_moves').waived_by)          # unchanged: the waiver stands
        self.invoice('2026-10-21', 100, post=False)
        c.action_refresh()
        self.assertFalse(self.item(c, 'draft_moves').waived_by)         # a second draft is not covered by the first waiver

    def test_05_day_close_and_one_close_per_period(self):
        c = self.close('day', '2026-10-15')
        self.assertEqual(c.date_from, c.date_to)
        self.assertEqual(self.item(c, 'draft_moves').status, 'ok')
        self.assertFalse(self.item(c, 'subledger'))                     # month-only checks are not asked every day
        with self.assertRaises(Exception):
            with self.cr.savepoint():
                self.close('day', '2026-10-15')
        with self.assertRaises(UserError):
            c.with_user(self.mgr).action_lock_books()                   # only a signed month locks the books

    # ---------------------------------------------------------------- reconciliation centre
    def test_06_centre_shows_each_reconciliation_only_to_who_may_read_it(self):
        everything = {c['code'] for c in self.env['ei.recon.centre'].sudo().get_overview()['cards']}
        self.assertTrue({'R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9', 'R10'} <= everything, everything)
        mine = {c['code']: c for c in self.env['ei.recon.centre'].with_user(self.acct).get_overview()['cards']}
        self.assertIn('R3', mine)
        self.assertNotIn('R1', mine)                                   # bank confirmations are not the accountant's records here
        self.assertEqual(mine['R3']['status'], 'attention')            # never signed off
        for k in ('receivable', 'payable'):
            s = self.sub(k, date=str(fields.Date.today()))
            s.with_user(self.mgr).action_sign()
        mine = {c['code']: c for c in self.env['ei.recon.centre'].with_user(self.acct).get_overview()['cards']}
        self.assertEqual(mine['R3']['status'], 'ok')
        cards = self.env['ei.recon.centre'].sudo().get_overview()['cards']
        self.assertEqual({c['status'] for c in cards if c['code'] in ('R9', 'R10')}, {'blocked'})   # never shown as agreeing
