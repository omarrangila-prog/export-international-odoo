"""The first real reports, on the SAME world the end-to-end journey builds (real role users, real records, no mocks). Every report total
must equal the figure the dashboard already shows from the same posted records, so a person never sees two answers to one question."""
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.ei_management_dashboard.tests.test_journey import TestJourney


@tagged('post_install', '-at_install', 'ei')
class TestReports(TestJourney):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.debtor = cls.env['res.partner'].create({'name': 'Rep Debtor'})
        cls.late = {}
        for key, days_late in (('current', -5), ('d1_30', 20), ('d31_60', 45), ('d61_90', 75), ('d90p', 120)):
            cls.late[key] = cls._invoice(cls.debtor, 10000 + days_late, cls.today - timedelta(days=days_late + 30), cls.today - timedelta(days=days_late))

    @classmethod
    def _invoice(cls, partner, amount, date, due):
        m = cls.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'invoice_date': date, 'invoice_date_due': due,
            'invoice_line_ids': [Command.create({'name': 'steel', 'quantity': 1, 'price_unit': amount, 'tax_ids': [Command.set([])]})]})
        m.action_post()
        return m

    def rows(self, model, user=None, domain=None):
        return self.env[model].with_user(user or self.ceo).search(domain or [])

    # ------------------------------------------------------------------ r01 receivables ageing
    def test_r01_ageing_total_and_bands_equal_the_dashboard(self):
        dash = self.env['ei.dashboard'].with_user(self.ceo).create({})
        rows = self.rows('ei.report.ar.aging')
        self.assertAlmostEqual(sum(rows.mapped('amount_residual')), dash.ar_open, places=2)
        for bucket, field in (('current', 'aging_current'), ('d1_30', 'aging_30'), ('d31_60', 'aging_60'), ('d61_90', 'aging_90'), ('d90p', 'aging_90plus')):
            self.assertAlmostEqual(sum(rows.filtered(lambda r: r.bucket == bucket).mapped('amount_residual')), dash[field], places=2, msg=bucket)

    def test_r02_each_open_item_lands_in_the_band_for_its_days_late(self):
        mine = self.rows('ei.report.ar.aging', domain=[('partner_id', '=', self.debtor.id)])
        self.assertEqual(len(mine), 5)
        for bucket, inv in self.late.items():
            row = mine.filtered(lambda r: r.move_id == inv)
            self.assertEqual(row.bucket, bucket, inv.name)
            self.assertEqual(row.days_overdue, max((self.today - inv.invoice_date_due).days, 0))
        self.assertEqual(mine.filtered(lambda r: r.bucket == 'current').days_overdue, 0)         # not yet due is 0, never negative
        self.assertEqual((mine[0].action_open_source()['res_model'], mine[0].action_open_source()['res_id']), ('account.move', mine[0].move_id.id))               # a row opens the invoice behind it
        paid = self.invoice                                                                       # the journey's invoice is fully paid
        self.assertFalse(self.rows('ei.report.ar.aging', domain=[('move_id', '=', paid.id)]))

    # ------------------------------------------------------------------ r03 book against bank
    def test_r03_book_balance_and_freshness_agree_with_home(self):
        today = fields.Date.context_today(self.env['ei.home'])
        banks = {b['name']: b for b in self.env['ei.home'].with_user(self.ceo)._banks()}
        rows = self.rows('ei.report.bank.freshness')
        self.assertEqual(len(rows), len(banks))
        for r in rows:
            self.assertAlmostEqual(r.book_balance, r.journal_id._ei_ledger_balance(today), places=2)
            self.assertEqual(r.freshness in ('stale', 'never'), banks[r.journal_id.name]['stale'], r.journal_id.name)
            self.assertEqual(r.age_days if r.age_days else None, banks[r.journal_id.name]['age_days'] or None)
        fresh = self.env['account.journal'].create({'name': 'Rep never confirmed', 'type': 'bank', 'code': 'RNV'})
        never = self.rows('ei.report.bank.freshness', domain=[('journal_id', '=', fresh.id)])
        self.assertEqual((never.freshness, never.age_days, never.confirmed_date), ('never', 0, False))         # no confirmation at all is its own state, not "0 days"

    # ------------------------------------------------------------------ r04 bank lines not in the books
    def test_r04_unmatched_lines_equal_the_bank_lines_still_to_deal_with(self):
        L = self.env['ei.bank.import.line'].sudo()
        todo = L.search([('state', 'in', ('new', 'proposed', 'verified', 'unidentified', 'duplicate'))])
        rows = self.rows('ei.report.bank.unmatched')
        self.assertEqual(sorted(rows.ids), sorted(todo.ids))
        self.assertAlmostEqual(sum(rows.mapped('amount')), sum(todo.mapped('amount')), places=2)
        waiting = L.search([('state', 'in', ('new', 'proposed', 'verified', 'unidentified')), ('amount', '>', 0)])
        home = self.env['ei.home'].with_user(self.ceo)
        figure = next((k for k in home.get_data()['kpis'] if k['key'] == 'waiting'), None)
        if figure:
            mine = rows.filtered(lambda r: r.direction == 'receipt' and r.state != 'duplicate')
            self.assertEqual(home._fmt(sum(mine.mapped('amount'))), figure['value'])
            self.assertEqual(len(mine), len(waiting))
        for r in rows:
            self.assertEqual(r.age_days, (self.today - r.date).days)
            self.assertEqual(r.age_bucket, 'd0_1' if r.age_days <= 1 else 'd2_7' if r.age_days <= 7 else 'd8_30' if r.age_days <= 30 else 'd31p')

    # ------------------------------------------------------------------ r05 contracts and lifting
    def test_r05_contract_report_equals_the_dashboard_and_the_parts_add_up(self):
        dash = self.env['ei.dashboard'].with_user(self.ceo).create({})
        live = self.rows('ei.report.contract.spread', domain=[('state', 'in', ('active', 'fulfilled'))])
        self.assertTrue(live)
        self.assertAlmostEqual(sum(live.mapped('gross_spread')), dash.gross_spread, places=2)          # same rounding, line by line
        self.assertAlmostEqual(sum(live.mapped('ordered_mtl')), dash.mtl_ordered, places=3)
        self.assertAlmostEqual(sum(live.mapped('allocated_mtl')), dash.mtl_allocated, places=3)
        self.assertAlmostEqual(sum(live.mapped('lifted_mtl')), dash.mtl_lifted, places=3)
        for r in live:
            self.assertLessEqual(r.lifted_mtl, r.allocated_mtl + 0.0005)
            self.assertAlmostEqual(r.lifted_mtl + r.not_lifted_mtl + r.not_promised_mtl, r.ordered_mtl, places=3)   # lifted is part of what was promised
        self.assertIn('NOT profit', self.env['ei.report.contract.spread']._fields['gross_spread'].help)

    def test_r06_lifting_counts_verified_loadings_only(self):
        rows = self.rows('ei.report.lifting')
        verified = self.env['ei.lifting'].sudo().search([('state', '=', 'verified')])
        self.assertAlmostEqual(sum(rows.mapped('lifted_mtl')), sum(verified.mapped('verified_mtl')), places=3)
        self.assertFalse([r for r in rows if r.state != 'verified' and r.lifted_mtl])               # a draft or reversed loading counts as zero
        self.assertEqual(len(rows), self.env['ei.lifting'].sudo().search_count([]))
        self.assertEqual(rows[0].action_open_source()['res_model'], 'ei.lifting')

    # ------------------------------------------------------------------ r07 who may read what
    def test_r07_money_reports_are_for_finance_roles_and_lifting_for_operations(self):
        for model in ('ei.report.ar.aging', 'ei.report.contract.spread'):
            for user in (self.dispatch, self.cashclerk, self.maker):
                with self.assertRaises(AccessError, msg=f'{model} {user.login}'):
                    self.env[model].with_user(user).search_count([])
        self.assertTrue(self.env['ei.report.bank.freshness'].with_user(self.officer).search_count([]) >= 0)     # a bank officer sees the bank reports
        with self.assertRaises(AccessError):
            self.env['ei.report.ar.aging'].with_user(self.officer).search_count([])
        self.assertTrue(self.env['ei.report.lifting'].with_user(self.dispatch).search_count([]) >= 1)
        with self.assertRaises(AccessError):
            self.env['ei.report.lifting'].with_user(self.cashclerk).search_count([])
        for model in ('ei.report.ar.aging', 'ei.report.bank.freshness', 'ei.report.bank.unmatched', 'ei.report.contract.spread', 'ei.report.lifting'):
            self.assertTrue(self.env['ir.access'].sudo().search_count([('model_id.model', '=', model), ('group_id', '=', False), ('domain', 'like', 'company_ids')]), f'{model} is limited to the user\'s companies')

    # ------------------------------------------------------------------ r08 the catalog
    def test_r08_catalog_is_honest_about_what_exists(self):
        cat = self.env['ei.report.catalog'].with_user(self.ceo).get_catalog()
        self.assertEqual(len({e['key'] for e in cat}), len(cat))
        self.assertTrue({e['status'] for e in cat} <= {'delivered', 'preview', 'partial', 'pending_source', 'not_built'})
        delivered = [e for e in cat if e['status'] == 'delivered']
        self.assertGreaterEqual(len(delivered), 6)
        for e in delivered:
            self.assertTrue(self.env.ref(e['action']), e['key'])                                    # a delivered report has a real screen
            self.assertTrue(e['can_open'], e['key'])
        for e in cat:
            if e['status'] in ('pending_source', 'not_built') and not e['action']:
                self.assertFalse(e['can_open'], e['key'])                                           # never a button that leads nowhere
            self.assertTrue(e['definition'] and e['source'])
        blocked = {e['key'] for e in cat if e['status'] == 'pending_source'}
        self.assertIn('tax_fbr', blocked)                                                            # needs FBR access
        previews = {e['key'] for e in cat if e['status'] == 'preview'}
        self.assertEqual(previews, {'pnl', 'balance_sheet', 'trial_balance', 'cash_flow'})           # worked out, but labelled: accounts not approved yet
        ops = {e['key']: e for e in self.env['ei.report.catalog'].with_user(self.dispatch).get_catalog()}
        self.assertTrue(ops['lifting']['can_open'])
        self.assertFalse(ops['ar_aging']['can_open'])

    def test_r09_favourites_belong_to_one_person(self):
        C = self.env['ei.report.catalog']
        self.assertTrue(C.with_user(self.ceo).toggle_favourite('ar_aging'))
        mine = {e['key']: e['favourite'] for e in C.with_user(self.ceo).get_catalog()}
        theirs = {e['key']: e['favourite'] for e in C.with_user(self.dispatch).get_catalog()}
        self.assertTrue(mine['ar_aging'])
        self.assertFalse(theirs['ar_aging'])
        self.assertFalse(C.with_user(self.ceo).toggle_favourite('ar_aging'))                         # a second press removes it
        with self.assertRaises(UserError):
            C.with_user(self.ceo).toggle_favourite('nonsense')

    def test_r10_only_the_figures_roles_may_export(self):
        for user in (self.ceo, self.bapprover):
            self.assertTrue(user.has_group('base.group_allow_export'), user.login)        # management and the finance approvers export what they may read
        for user in (self.dispatch, self.cashclerk, self.maker, self.officer):
            self.assertFalse(user.has_group('base.group_allow_export'), user.login)       # operators and data entry do not
