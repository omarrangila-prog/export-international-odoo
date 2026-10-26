"""The Overview pieces of Home (flows against the previous period, who owes most, recent documents) on the SAME world the
end-to-end journey builds: real role users, real records, no mocks."""
import re
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.ei_management_dashboard.tests.test_journey import TestJourney
from odoo.addons.ei_ui_theme.models.overview import PERIODS


@tagged('post_install', '-at_install', 'ei')
class TestOverview(TestJourney):
    """Re-uses the journey fixture; the journey's own tests run in their own class, not here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.rich = cls.env['res.partner'].create({'name': 'Ov Big Debtor'})
        cls.small = cls.env['res.partner'].create({'name': 'Ov Small Debtor'})
        cls.cur_inv = cls.invoice_for(cls.rich, 300000, cls.today - timedelta(days=2), cls.today - timedelta(days=1))     # this period, already late
        cls.prev_inv = cls.invoice_for(cls.rich, 100000, cls.today - timedelta(days=20), cls.today + timedelta(days=10))  # the 14 days before
        cls.small_inv = cls.invoice_for(cls.small, 50000, cls.today - timedelta(days=3), cls.today + timedelta(days=20))

    @classmethod
    def invoice_for(cls, partner, amount, date, due):
        m = cls.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'invoice_date': date, 'invoice_date_due': due,
            'invoice_line_ids': [Command.create({'name': 'steel', 'quantity': 1, 'price_unit': amount, 'tax_ids': [Command.set([])]})]})
        m.action_post()
        return m

    def home(self, user, period=None):
        return self.env['ei.home'].with_user(user).get_data(period)

    def flow(self, user, key, period=None):
        return next((f for f in self.home(user, period)['flows'] if f['key'] == key), None)

    def money(self, v):
        return self.env['ei.home'].with_user(self.ceo)._fmt(v)

    # ------------------------------------------------------------------ o01 the period
    def test_o01_periods_are_server_defined_equal_length_and_adjacent(self):
        H = self.env['ei.home'].with_user(self.ceo)
        self.assertEqual(H._range('nonsense')[0], '14d')                  # the client never chooses dates
        self.assertEqual(self.home(self.ceo, "'; drop table")['period']['key'], '14d')
        for key, n in PERIODS:
            k, start, end, pstart, pend = H._range(key)
            self.assertEqual((k, end), (key, self.today))
            if key == 'month':
                self.assertEqual(start, self.today.replace(day=1))
                self.assertEqual((pstart.day, pend < start), (1, True))
                self.assertLessEqual((pend - pstart).days, (end - start).days)
            else:
                self.assertEqual(((end - start).days + 1, (pend - pstart).days + 1), (n, n))
                self.assertEqual(pend, start - timedelta(days=1))          # the period before ends the day before this one starts
        p = self.home(self.ceo)['period']
        self.assertEqual([o['key'] for o in p['options']], ['7d', '14d', '30d', 'month'])

    def test_o02_a_change_is_only_a_percentage_when_there_is_something_to_compare(self):
        d = self.env['ei.home']._delta
        self.assertEqual((d(300, 100)['text'], d(300, 100)['dir'], d(300, 100)['tone']), ('+200%', 'up', 'ok'))
        self.assertEqual((d(50, 100)['text'], d(50, 100)['dir'], d(50, 100)['tone']), ('-50%', 'down', 'bad'))
        self.assertEqual((d(100, 100)['dir'], d(100.2, 100)['dir']), ('flat', 'flat'))
        self.assertEqual((d(10, 0)['dir'], d(10, 0)['text']), ('new', 'New'))               # no invented percentage
        self.assertEqual((d(0, 0)['dir'], d(0, 0)['text']), ('flat', 'No activity'))
        self.assertEqual(d(0, 100)['dir'], 'down')

    # ------------------------------------------------------------------ o03 the flows are the records
    def test_o03_invoiced_equals_the_posted_invoices_and_compares_with_the_period_before(self):
        f = self.flow(self.ceo, 'invoiced', '14d')
        moves = self.env['account.move'].search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                                                 ('invoice_date', '>=', self.today - timedelta(days=13)), ('invoice_date', '<=', self.today)])
        self.assertEqual(f['value'], sum(moves.mapped('amount_total_signed')))
        self.assertIn(self.cur_inv, moves)
        self.assertNotIn(self.prev_inv, moves)
        self.assertEqual(f['text'], self.money(f['value']))
        before = self.env['account.move'].search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                                                  ('invoice_date', '>=', self.today - timedelta(days=27)), ('invoice_date', '<=', self.today - timedelta(days=14))])
        self.assertEqual(f['prev'], sum(before.mapped('amount_total_signed')))
        self.assertIn(self.prev_inv, before)
        self.assertEqual(f['delta']['dir'], 'up')
        self.assertEqual(len(f['series']), 14)
        self.assertEqual(sum(s['v'] for s in f['series']), f['value'])                      # the daily points add up to the card
        by_day = {s['iso']: s['v'] for s in f['series']}
        day = self.today - timedelta(days=2)
        self.assertEqual(by_day[fields.Date.to_string(day)], sum(m.amount_total_signed for m in moves if m.invoice_date == day))

    def test_o04_received_and_lifted_equal_their_records(self):
        f = self.flow(self.ceo, 'collected', '30d')
        lines = self.env['ei.bank.import.line'].search([('state', '=', 'posted'), ('amount', '>', 0), ('date', '>=', self.today - timedelta(days=29)), ('date', '<=', self.today)])
        self.assertEqual(f['value'], sum(lines.mapped('amount')))
        self.assertEqual(f['color'], 's2')
        lift = self.flow(self.ceo, 'lifted', '7d')
        self.assertEqual((lift['text'], lift['unit']), ('4.000 MTL', 'mtl'))                 # the 4 MTL of the journey, dispatched today
        self.assertEqual(lift['delta']['dir'], 'new')

    def test_o05_a_card_is_absent_when_the_role_may_not_see_it(self):
        keys = lambda u: [f['key'] for f in self.home(u)['flows']]
        self.assertEqual(sorted(keys(self.ceo)), ['collected', 'invoiced', 'lifted'])
        self.assertEqual(keys(self.dispatch), ['lifted'])
        self.assertEqual(keys(self.cashclerk), [])
        self.assertIn('invoiced', keys(self.bapprover))                                    # a bank approver is a finance role
        with self.assertRaises(AccessError):
            self.env['ei.home'].with_user(self.dispatch).open_flow('invoiced', '14d')
        with self.assertRaises(AccessError):
            self.env['ei.home'].with_user(self.cashclerk).open_flow('lifted', '14d')

    def test_o06_every_card_opens_exactly_the_records_it_added_up(self):
        H = self.env['ei.home'].with_user(self.ceo)
        for key, model, amount_field in (('invoiced', 'account.move', 'amount_total_signed'), ('collected', 'ei.bank.import.line', 'amount'),
                                         ('lifted', 'ei.lifting', 'verified_mtl')):
            act = H.open_flow(key, '30d')
            self.assertEqual((act['type'], act['res_model']), ('ir.actions.act_window', model))
            recs = self.env[model].with_user(self.ceo).search(act['domain'])
            self.assertEqual(round(sum(recs.mapped(amount_field)), 2), round(self.flow(self.ceo, key, '30d')['value'], 2), key)
        with self.assertRaises(AccessError):
            H.open_flow('nonsense', '30d')

    # ------------------------------------------------------------------ o07 who owes most
    def test_o07_who_owes_most_adds_up_to_what_customers_owe(self):
        top = self.home(self.ceo)['top_owing']
        dash = self.env['ei.dashboard'].with_user(self.ceo).create({})
        self.assertEqual(top['total_text'], self.money(dash.ar_open))
        self.assertEqual([r['name'] for r in top['rows']][:2], ['Ov Big Debtor', 'Ov Small Debtor'])
        self.assertEqual(top['rows'][0]['amount'], 400000)
        self.assertEqual(top['rows'][1]['amount'], 50000)
        self.assertEqual(top['rows'][0]['pct'], round(100 * 400000 / dash.ar_open))
        self.assertTrue(all(r['amount'] > 0 for r in top['rows']))                           # a paid customer never appears
        self.assertNotIn(self.customer.name, [r['name'] for r in top['rows']])
        self.assertLessEqual(sum(r['pct'] for r in top['rows']), 100 + len(top['rows']))
        self.assertIsNone(self.home(self.dispatch)['top_owing'])                            # money is for finance roles

    # ------------------------------------------------------------------ o08 recent documents
    def test_o08_recent_documents_by_role(self):
        r = self.home(self.ceo)['recent']
        self.assertEqual(r['kind'], 'invoices')
        by = {x['name']: x for x in r['rows']}
        self.assertEqual(by[self.cur_inv.name]['status'], 'Overdue')                         # unpaid and past its due date
        self.assertEqual(by[self.cur_inv.name]['tone'], 'bad')
        self.assertEqual(by[self.small_inv.name]['tone'], 'warning')                         # unpaid, not yet due
        self.assertEqual(by[self.invoice.name]['tone'], 'ok')                                # the journey's invoice is paid
        self.assertEqual([x['res_id'] for x in r['rows']], self.env['account.move'].search(
            [('move_type', '=', 'out_invoice'), ('state', '=', 'posted')], order='invoice_date desc, id desc', limit=6).ids)
        for row in r['rows']:
            self.assertTrue(self.env['ei.search'].with_user(self.ceo).open(row['model'], row['res_id']))
        ops = self.home(self.dispatch)['recent']
        self.assertEqual(ops['kind'], 'loadings')
        self.assertEqual(ops['rows'][0]['name'], self.lift.name)
        self.assertEqual((ops['rows'][0]['amount'], ops['rows'][0]['tone']), ('4.000 MTL', 'ok'))
        self.assertIsNone(self.home(self.cashclerk)['recent'])

    # ------------------------------------------------------------------ o09 the page as a whole
    def test_o09_banks_total_and_layouts(self):
        d = self.home(self.ceo)
        self.assertEqual(d['banks_total'], self.money(sum(b['amount'] for b in d['banks'])))
        kpi = next((k for k in d['kpis'] if k['key'] == 'bank'), None)
        if kpi:
            self.assertEqual(kpi['value'], d['banks_total'])
        known = {'hero', 'flows', 'kpis', 'alerts', 'work', 'charts', 'recent', 'activity', 'quick', 'system'}
        for user in (self.ceo, self.bapprover, self.officer, self.maker, self.dispatch, self.cashclerk, self.capprover):
            lay = self.home(user)['layout']
            self.assertTrue(set(lay) <= known, (user.login, lay))
            self.assertIn('hero', lay)
            self.assertEqual(len(lay), len(set(lay)))

    # ------------------------------------------------------------------ o10 money stays with the roles that may see it
    def test_o10_bank_balances_and_invoice_messages_are_for_finance_roles_only(self):
        """Found with realistic data: an invoice's change messages carry its amounts ("Rs. 0.00 -> Rs. -1,055,000.00") and the
        activity feed showed them to operators, and the bank-line officer saw what the banks hold. Neither is theirs to see."""
        self.cur_inv.message_post(body='Total changed from Rs. 100,000.00 to Rs. 300,000.00', message_type='comment')
        entry = self.env['account.move'].create({'move_type': 'entry', 'journal_id': self.bank.id})
        entry.message_post(body='Journal Item #94 created: Receivable (Account) Rs. 0.00 -> Rs. -1,055,000.00', message_type='comment')
        money = re.compile(r'Rs\.\s?[\d,]+\.\d\d')
        for user in (self.dispatch, self.cashclerk, self.maker, self.officer):
            feed = self.home(user)['activity']
            self.assertFalse([a for a in feed if a['model'] == 'account.move'], user.login)
            self.assertFalse([a['text'] for a in feed if money.search(a['text'])], user.login)
        ceo_feed = self.home(self.ceo)['activity']
        self.assertIn(self.cur_inv.id, [a['res_id'] for a in ceo_feed if a['model'] == 'account.move'])      # finance still sees the invoice
        self.assertNotIn(entry.id, [a['res_id'] for a in ceo_feed if a['model'] == 'account.move'])           # a journal entry is bookkeeping noise
        self.assertTrue(self.home(self.ceo)['banks'])
        officer = self.home(self.officer)
        self.assertEqual((officer['banks'], officer['banks_total']), ([], ''))
