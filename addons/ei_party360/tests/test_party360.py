"""Party 360 acts on the SAME world the end-to-end journey builds (real role users, real records, no mocks):
contract 100 MTL -> DA-5501 10 MTL -> daily order -> 4 MTL lifted -> supplier bill -> customer invoice -> bank receipt."""
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.ei_management_dashboard.tests.test_journey import TestJourney


@tagged('post_install', '-at_install', 'ei')
class TestParty360(TestJourney):
    """Re-uses the journey fixture; the journey's own tests run in their own class, not here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.P = cls.env['ei.party360']

    def _as(self, user, ctx=None):
        return self.env['ei.party360'].with_user(user).with_context(**(ctx or {}))

    @staticmethod
    def _m(data, key):
        return next((m for m in data['metrics'] if m['key'] == key), None)

    # ------------------------------------------------------------- P01 the numbers are the real numbers
    def test_p01_customer_page_matches_the_journey(self):
        d = self._as(self.ceo).get_data(self.customer.id)
        self.assertEqual(d['partner']['name'], self.customer.name)
        self.assertEqual([c['code'] for c in d['partner']['codes']], ['1.03'], "exact legacy code text")
        self.assertEqual(self._m(d, 'm_approved')['text'], '10.000 MTL')
        self.assertEqual(self._m(d, 'm_ordered')['text'], '10.000 MTL')
        self.assertEqual(self._m(d, 'm_lifted')['text'], '4.000 MTL')           # T04: 10 requested, 4 lifted
        self.assertEqual(self._m(d, 'm_remaining')['text'], '6.000 MTL')        # ... 6 remain
        self.assertEqual(self._m(d, 'f_invoices')['count'], 1)
        self.assertEqual(self._m(d, 'b_in')['count'], 1)
        self.assertIn('840,000.00', self._m(d, 'b_in')['text'])
        self.assertEqual(self._m(d, 'l_to_invoice')['count'], 0, "the 4 MTL are already invoiced")

    def test_p02_supplier_page(self):
        d = self._as(self.ceo).get_data(self.parent.id)
        self.assertEqual(self._m(d, 'd_contracts')['count'], 1)
        self.assertEqual(self._m(d, 'm_remaining')['text'], '6.000 MTL')
        ap = self._m(d, 'f_ap')
        self.assertIn('800,000.00', ap['text'], "posted supplier bill, not yet paid")
        self.assertEqual(d['partner']['codes'], [], "a parent company has no approved old code here")

    # ------------------------------------------------------------- P03 chain
    def test_p03_chain_stages_follow_the_documents(self):
        d = self._as(self.ceo).get_data(self.customer.id)
        self.assertEqual(len(d['chains']), 1)
        st = {s['key']: s for s in d['chains'][0]['stages']}
        self.assertEqual(d['chains'][0]['da'], 'DA-5501')
        self.assertEqual(st['contract']['tone'], 'done')
        self.assertEqual(st['da']['tone'], 'done')
        self.assertEqual(st['order']['tone'], 'done')
        self.assertEqual(st['lift']['tone'], 'active', "4 of 10 is progress, not done")
        self.assertIn('4.000 MTL of 10.000 MTL lifted', st['lift']['text'])
        self.assertEqual(st['invoice']['tone'], 'done')
        # the payment stage mirrors Odoo's own payment state of the posted invoice
        self.assertEqual(self.invoice.payment_state, 'paid')
        self.assertEqual(st['payment']['tone'], 'done')

    def test_p04_a_supplier_invoice_alone_is_not_lifting(self):
        """T-lifting rule: the supplier bill (4 MTL) exists, but only the verified loading counts as lifted."""
        self.assertTrue(self.bill.state == 'posted')
        d = self._as(self.ceo).get_data(self.parent.id)
        self.assertEqual(self._m(d, 'm_lifted')['text'], '4.000 MTL')
        self.assertEqual(self.lift.state, 'verified')

    # ------------------------------------------------------------- P05 figures reconcile with the dashboard (T18)
    def test_p05_party_ledger_equals_dashboard(self):
        for partner in (self.customer, self.parent):
            dash = self.env['ei.dashboard'].with_user(self.ceo).create({'partner_id': partner.id})
            d = self._as(self.ceo).get_data(partner.id)
            ar = self._m(d, 'f_ar')['text'].replace(',', '')
            ap = self._m(d, 'f_ap')['text'].replace(',', '')
            self.assertIn('%.2f' % dash.ar_open, ar)
            self.assertIn('%.2f' % dash.ap_open, ap)

    # ------------------------------------------------------------- P06 the drill-down shows exactly what was counted
    def test_p06_every_figure_opens_its_records(self):
        P = self._as(self.ceo)
        for partner in (self.customer, self.parent):
            d = P.get_data(partner.id)
            for m in d['metrics']:
                act = P.open_records(partner.id, m['key'])
                n = self.env[act['res_model']].with_user(self.ceo).search_count(act['domain'])
                self.assertEqual(n, m['count'], "%s: the figure and its records disagree" % m['key'])

    # ------------------------------------------------------------- P07 suggestion is not money
    def test_p07_suggested_bank_money_is_not_counted_as_received(self):
        csv = ("Date,Description,Reference,Debit,Credit,Balance\n"
               "08/10/2026,RAAST FROM ARIF PATANWALA,TX901,,100000,940000\n").encode()
        imp = self.env['ei.bank.import'].with_user(self.officer).import_file(self.bank, 'oct2.csv', csv, 840000, 940000)
        imp.with_user(self.officer).action_suggest()
        line = imp.line_ids
        self.assertEqual(line.suggested_partner_id, self.customer, "setup: the alias should suggest the customer")
        self.assertFalse(line.partner_id)
        d = self._as(self.ceo).get_data(self.customer.id)
        self.assertEqual(self._m(d, 'b_in')['count'], 1, "still only the confirmed receipt")
        self.assertEqual(self._m(d, 'b_suggested')['count'], 1)
        ev = [e for e in d['timeline'] if e['kind'] == 'bank' and 'not confirmed' in e['detail']]
        self.assertTrue(ev, "the timeline labels it as a suggestion")

    # ------------------------------------------------------------- P08 role limits, no false zeros (T12-style)
    def test_p08_cash_clerk_sees_only_what_the_role_allows(self):
        d = self._as(self.cashclerk).get_data(self.customer.id)
        keys = {m['key'] for m in d['metrics']}
        self.assertFalse(keys & {'m_approved', 'm_lifted', 'b_in', 'f_ar', 'd_contracts'}, keys)
        self.assertTrue(d['hidden'], "hidden sections are named, not shown as zero")
        self.assertIsNone(d['chains'])
        self.assertFalse([e for e in d['timeline'] if e['kind'] in ('contract', 'lifting', 'bank')])
        with self.assertRaises(AccessError):
            self._as(self.cashclerk).open_records(self.customer.id, 'm_approved')
        with self.assertRaises(AccessError):
            self._as(self.cashclerk).open_record('ei.da', self.da.id)

    def test_p09_only_listed_record_types_can_be_opened(self):
        with self.assertRaises(AccessError):
            self._as(self.ceo).open_record('res.users', 1)
        act = self._as(self.ceo).open_record('ei.da', self.da.id)
        self.assertEqual((act['res_model'], act['res_id']), ('ei.da', self.da.id))
        with self.assertRaises(UserError):
            self._as(self.ceo).open_records(self.customer.id, 'nope')

    # ------------------------------------------------------------- P10 search
    def test_p10_search_matches_code_text_exactly(self):
        S = self._as(self.ceo)
        hit = S.search_parties('1.03')
        self.assertEqual(hit[0]['partner_id'], self.customer.id)
        self.assertIn('1.03', hit[0]['reason'])
        # '1.3' must NOT find 1.03 (text, not number)
        self.assertNotIn(self.customer.id, [r['partner_id'] for r in S.search_parties('1.3')])
        self.assertEqual(S.search_parties('a'), [], "one letter is too short")
        self.assertEqual(S.search_parties('%%'), [], "wildcards are searched literally")
        # a code that is not linked to a party is offered as a code, not silently turned into one
        unlinked = [r for r in S.search_parties('4.20') if not r['partner_id']]
        self.assertTrue(unlinked and unlinked[0]['code_id'])
        self.assertTrue(unlinked[0]['title'].startswith('4.20 '), unlinked[0]['title'])

    def test_p10b_real_parties_come_before_unlinked_codes(self):
        # 'ARIF' matches the linked customer (by name and code) AND other old codes that have no party yet
        hit = self._as(self.ceo).search_parties('ARIF')
        flags = [bool(r['partner_id']) for r in hit]
        self.assertTrue(flags[0], "the first suggestion is the real party")
        self.assertEqual(flags, sorted(flags, reverse=True), "no unlinked code before a real party")
        self.assertLessEqual(sum(1 for f in flags if not f), 4, "unlinked codes cannot flood the list")

    def test_p11_search_by_approved_alias(self):
        hit = self._as(self.ceo).search_parties('ARIF PATAN')
        self.assertIn(self.customer.id, [r['partner_id'] for r in hit])

    # ------------------------------------------------------------- P12 it only reads
    def test_p12_opening_a_page_changes_nothing(self):
        models = ['ei.da', 'ei.lifting', 'ei.daily.order', 'account.move', 'ei.bank.import.line', 'ei.dashboard']
        before = {m: self.env[m].sudo().search_count([]) for m in models}
        stamp = self.da.write_date
        self._as(self.ceo).get_data(self.customer.id)
        self._as(self.ceo).search_parties('Parent')
        self.assertEqual(before, {m: self.env[m].sudo().search_count([]) for m in models})
        self.assertEqual(self.da.write_date, stamp)

    # ------------------------------------------------------------- P13 company isolation (T13)
    def test_p13_another_company_sees_none_of_it(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        self.ceo.write({'company_ids': [Command.link(other.id)]})
        P = self._as(self.ceo, {'allowed_company_ids': [other.id]})
        # the customer belongs to the first company: its page cannot even be opened from the other one
        self.assertTrue(self.customer.company_id)
        with self.assertRaises(AccessError):
            P.get_data(self.customer.id)
        # the parent company is a shared contact: opening it from the other company shows none of our data
        self.assertFalse(self.parent.company_id)
        d = P.get_data(self.parent.id)
        for key in ('m_approved', 'm_lifted', 'd_contracts', 'b_in', 'f_ap'):
            m = self._m(d, key)
            self.assertTrue(m is None or m['count'] == 0, "%s leaked across companies" % key)
        self.assertEqual(d['chains'], [])
        self.assertEqual(d['timeline'], [])

    # ------------------------------------------------------------- P14 query budget
    def test_p14_page_cost_is_bounded(self):
        self.env.invalidate_all()
        self.cr.flush() if hasattr(self.cr, 'flush') else None
        n0 = self.cr.sql_log_count
        self._as(self.ceo).get_data(self.customer.id)
        used = self.cr.sql_log_count - n0
        self.assertLess(used, 220, "Party 360 used %s queries; look for an N+1" % used)
