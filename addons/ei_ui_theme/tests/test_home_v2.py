"""The redesigned Home: role profiles, real figures, the My Work engine, universal search, CEO drill-downs, theme.

Every assertion is about real records created in setUpClass (acting through real role users); nothing is mocked except
the HTTP cookie in the dark-theme test."""
from types import SimpleNamespace
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ei_legacy_master.tests.test_parsing import source_bytes
from odoo.addons.ei_ui_theme.models.work import WORK


@tagged('post_install', '-at_install', 'ei')
class TestHomeV2(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([cls.env.ref(g).id for g in gs] or [cls.env.ref('base.group_user').id])]})
        cls.cash = mk('v_cash', 'ei_cashbook.group_ei_cash_clerk')
        cls.maker = mk('v_maker', 'ei_contract_da.group_ei_contract_staff')
        cls.approver = mk('v_approver', 'ei_contract_da.group_ei_contract_approver', 'ei_daily_orders.group_ei_order_approver')
        cls.approver2 = mk('v_approver2', 'ei_contract_da.group_ei_contract_approver')
        cls.ceo = mk('v_ceo', 'ei_management_dashboard.group_ei_management')
        cls.finance = mk('v_finance', 'account.group_account_manager', 'ei_bank_operations.group_ei_bank_approver', 'ei_cashbook.group_ei_cash_approver')
        cls.sysadmin = mk('v_sysadmin', 'base.group_system', 'ei_legacy_master.group_ei_user')
        cls.dispatch = mk('v_dispatch', 'ei_material_lifting.group_ei_dispatch_officer')
        cls.plain = mk('v_plain')
        cls.importer = mk('v_importer', 'ei_legacy_master.group_ei_importer')
        cls.mapper = mk('v_mapper', 'ei_legacy_master.group_ei_mapping_approver')
        cls.auditor = mk('v_auditor', 'ei_legacy_master.group_ei_auditor')
        prod = cls.env['product.product'].create({'name': 'V2 coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        cls.parent = cls.env['res.partner'].create({'name': 'V2 Parent Mill'})

        def reviewed_contract(maker, ref):
            c = cls.env['ei.contract'].with_user(maker).create({'parent_partner_id': cls.parent.id, 'contract_ref': ref, 'line_ids': [Command.create({
                'product_id': prod.id, 'ordered_mtl': 5, 'purchase_rate': 1, 'sale_rate': 2})]})
            cls.env['ir.attachment'].create({'name': 'c', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
            c.with_user(maker).action_review()
            return c
        cls.reviewed_contract = staticmethod(reviewed_contract)
        cls.contract = reviewed_contract(cls.maker, 'V2-A')           # made by maker -> an approver can act on it
        cls.own = reviewed_contract(cls.approver, 'V2-OWN')           # made by the approver -> maker-checker: not theirs to approve
        cls.Home, cls.Work = cls.env['ei.home'], cls.env['ei.work']

    def home(self, user):
        return self.Home.with_user(user).get_data()

    def tasks(self, user, **kw):
        return self.Work.with_user(user).tasks(**kw)

    def item(self, user, contract, **kw):
        return next((t for t in self.tasks(user, **kw)['items'] if t['model'] == 'ei.contract' and t['res_id'] == contract.id), None)

    def age(self, rec, days):
        self.env.cr.execute("UPDATE %s SET write_date = write_date - interval '%d days' WHERE id = %%s" % (rec._table, days), (rec.id,))
        rec.invalidate_recordset()

    # ------------------------------------------------------------------ role profiles
    def test_01_each_role_gets_its_own_layout_and_figures(self):
        want = {self.ceo: 'executive', self.finance: 'finance', self.approver: 'contract', self.cash: 'data_entry',
                self.dispatch: 'logistics', self.sysadmin: 'admin', self.plain: 'general'}
        for user, profile in want.items():
            d = self.home(user)
            self.assertEqual(d['profile'], profile, user.login)
            self.assertEqual(sorted(d['layout']), sorted(set(d['layout'])), 'no section is listed twice')
        ceo_layout = self.home(self.ceo)['layout']
        self.assertEqual(ceo_layout[:2], ['summary', 'decide'])             # the first screen is the figures and what needs a person
        self.assertLess(ceo_layout.index('hero'), ceo_layout.index('work'))  # then the overview, before the long work list
        self.assertEqual(self.home(self.approver)['layout'][0], 'work')     # workflow first
        self.assertEqual(self.home(self.sysadmin)['layout'][0], 'system')

    def test_02_money_is_only_for_finance_and_management(self):
        money = {'bank', 'ar', 'ap', 'cash', 'collected', 'waiting', 'spread'}
        for user in (self.approver, self.cash, self.dispatch, self.maker):
            d = self.home(user)
            self.assertFalse({k['key'] for k in d['kpis']} & money, user.login)
            self.assertFalse({'cashflow', 'aging'} & set(d['charts']), user.login)
        self.assertEqual({k['key'] for k in self.home(self.ceo)['kpis']}, {'bank', 'ar', 'ap', 'collected', 'waiting', 'cash', 'spread', 'recon'})
        fin = {k['key'] for k in self.home(self.finance)['kpis']}
        self.assertTrue({'ar', 'ap', 'bank'} <= fin)
        self.assertNotIn('spread', fin)

    def test_03_user_without_a_role_gets_a_polite_empty_page(self):
        d = self.home(self.plain)
        self.assertTrue(d['empty'])
        self.assertEqual((d['kpis'], d['quick'], d['work']['items'], d['alerts']), ([], [], [], []))

    def test_04_ceo_can_open_every_figure_and_a_reader_cannot_change_the_books(self):
        """Regression (25 Oct 2026): the CEO saw the money figures but got an access error opening the records."""
        d = self.home(self.ceo)
        for k in d['kpis']:
            act = self.Home.with_user(self.ceo).open_kpi(k['key'])
            self.assertEqual(act['type'], 'ir.actions.act_window', k['key'])
            self.assertTrue(act['views'], 'a window action without `views` crashes the Odoo 20 web client')
            self.env[act['res_model']].with_user(self.ceo).search_count(act['domain'] if 'domain' in act else [])
        # owner's decision (27 Oct 2026): the CEO may also prepare entries; the read-only role still cannot touch the books
        self.assertFalse(self.env['account.move.line'].with_user(self.auditor).has_access('write'))

    def test_05_home_is_read_only(self):
        models = ('ei.contract', 'ei.da', 'ei.bank.import', 'ei.cash.voucher', 'account.move', 'ei.work.snooze', 'mail.activity')
        before = [self.env[m].search_count([]) for m in models]
        for u in (self.approver, self.ceo, self.finance, self.sysadmin):
            self.home(u)
        self.assertEqual(before, [self.env[m].search_count([]) for m in models])

    def test_06_system_checks_only_for_administrators(self):
        self.assertIsNone(self.home(self.ceo)['system'])
        labels = ' '.join(c['label'] for c in self.home(self.sysadmin)['system']['checks'])
        self.assertIn('PDF engine', labels)
        self.assertIn('Staff accounts', labels)

    def test_06b_staff_without_a_role_are_counted_correctly(self):
        """A role reaches group_ei_user through its own group; only people with no role at all are 'without a role'."""
        text = next(c['text'] for c in self.home(self.sysadmin)['system']['checks'] if c['label'] == 'Staff accounts')
        staff = self.env['res.users'].search([('share', '=', False), ('active', '=', True)])
        expected = len(staff.filtered(lambda u: not u.has_group('ei_legacy_master.group_ei_user')))
        self.assertIn('%s without an Export International role' % expected, text)
        self.assertNotIn(self.approver.login, text)
        self.assertLess(expected, len(staff), 'someone has a role: not everybody is "without a role"')

    def test_07_pipeline_counts_are_real_and_money_free_for_operators(self):
        stages = {s['key']: s for s in self.home(self.approver)['pipeline']}
        self.assertEqual(stages['contract']['waiting'], self.env['ei.contract'].search_count([('state', '=', 'reviewed')]))
        self.assertGreaterEqual(stages['contract']['waiting'], 2)
        self.assertEqual(stages['contract']['tone'], 'warning')
        self.assertNotIn('payment', stages)                          # no payment stage without bank or ledger access
        for key in stages:
            act = self.Home.with_user(self.approver).open_stage(key)
            self.assertTrue(act['views'])

    def test_08_alerts_are_only_raised_by_real_problems(self):
        self.assertEqual([a for a in self.home(self.ceo)['alerts'] if a['key'] in ('dup_payment', 'unidentified', 'intake_mismatch', 'bank_diff')], [])
        for a in self.home(self.ceo)['alerts']:
            self.assertGreater(a['count'], 0)
            self.assertTrue(self.Home.with_user(self.ceo).open_alert(a['key'])['views'])

    # ------------------------------------------------------------------ My Work
    def test_10_a_task_is_a_real_record_with_priority_party_and_next_step(self):
        t = self.item(self.approver, self.contract)
        self.assertTrue(t)
        self.assertEqual((t['verb'], t['priority'], t['status'], t['can_act']), ('Approve', 'low', 'open', True))
        self.assertEqual(t['party'], 'V2 Parent Mill')
        self.assertTrue(t['next'] and t['age_text'] == 'New today')
        self.assertTrue(self.Work.with_user(self.approver).open_task('ei.contract', self.contract.id)['views'])

    def test_11_maker_checker_the_preparer_is_not_asked_to_approve_their_own_work(self):
        self.assertIsNone(self.item(self.approver, self.own))
        self.assertGreaterEqual(self.tasks(self.approver)['counts']['others'], 1)
        self.assertTrue(self.item(self.approver2, self.own))          # a different approver can

    def test_12_priority_follows_the_stated_rules(self):
        self.age(self.contract, 1)
        self.assertEqual(self.item(self.approver, self.contract)['priority'], 'medium')
        self.age(self.contract, 3)
        t = self.item(self.approver, self.contract)
        self.assertEqual(t['priority'], 'high')
        self.assertTrue(t['overdue'])
        self.assertIn('Overdue', self.tasks(self.approver)['rules'])

    def test_13_the_ceo_sees_approvals_only_when_stuck_and_cannot_approve(self):
        self.assertIsNone(self.item(self.ceo, self.contract), 'a fresh task is not the CEO\'s business')
        self.age(self.contract, 5)
        t = self.item(self.ceo, self.contract)
        self.assertTrue(t and t['view_only'] and not t['can_act'] and t['overdue'])
        self.assertFalse(self.tasks(self.ceo)['oversight'], 'the CEO may prepare entries now, so Home is not "oversight only"')
        self.assertTrue(self.tasks(self.auditor)['oversight'])
        self.assertFalse(t['can_assign'])

    def test_14_nothing_for_a_user_who_may_not_see_it(self):
        self.assertEqual(self.tasks(self.cash)['items'], [])
        with self.assertRaises(AccessError):
            self.Work.with_user(self.cash).open_task('ei.contract', self.contract.id)
        with self.assertRaises(AccessError):
            self.Work.with_user(self.approver).open_task('res.users', 1)

    def test_15_snooze_hides_for_that_user_only_and_can_be_undone(self):
        W = self.Work.with_user(self.approver)
        W.snooze('ei.contract', self.contract.id, 3)
        self.assertIsNone(self.item(self.approver, self.contract))
        self.assertTrue(self.item(self.approver, self.contract, show_snoozed=True))
        self.assertTrue(self.item(self.approver2, self.contract), 'another person still sees it')
        self.assertEqual(self.tasks(self.approver)['counts']['snoozed'], 1)
        W.unsnooze('ei.contract', self.contract.id)
        self.assertTrue(self.item(self.approver, self.contract))
        with self.assertRaises(UserError):
            W.snooze('ei.contract', self.contract.id, 30)
        W.snooze('ei.contract', self.contract.id, 1)
        W.snooze('ei.contract', self.contract.id, 7)                     # re-snoozing moves the date, no duplicate
        self.assertEqual(self.env['ei.work.snooze'].search_count([('user_id', '=', self.approver.id)]), 1)

    def test_16_assign_creates_a_real_odoo_reminder_for_a_person_who_can_do_it(self):
        people = self.Work.with_user(self.approver).assignable_users('ei.contract', self.contract.id)
        self.assertIn(self.approver2.id, [p['id'] for p in people])
        self.assertNotIn(self.cash.id, [p['id'] for p in people])
        self.Work.with_user(self.approver).assign('ei.contract', self.contract.id, self.approver2.id, False, 'please look today')
        act = self.env['mail.activity'].search([('res_model', '=', 'ei.contract'), ('res_id', '=', self.contract.id)])
        self.assertEqual((act.user_id, act.note and 'please look today' in act.note), (self.approver2, True))
        mine = self.item(self.approver2, self.contract)
        self.assertTrue(mine['assignee_me'] and mine['my_activity'])
        self.assertTrue(self.item(self.approver, self.contract)['assignee'] == self.approver2.name)
        with self.assertRaises(UserError):                                # never to someone who cannot complete the step
            self.Work.with_user(self.approver).assign('ei.contract', self.contract.id, self.cash.id)
        with self.assertRaises(AccessError):                              # a reader cannot hand out work on records they cannot change
            self.Work.with_user(self.auditor).assign('ei.contract', self.contract.id, self.approver2.id)

    def test_16b_assigning_a_task_that_is_already_done_says_so(self):
        c = self.contract
        c.with_user(self.approver2).action_approve()          # the step is done by someone else meanwhile
        with self.assertRaises(UserError):
            self.Work.with_user(self.approver).assignable_users('ei.contract', c.id)

    def test_17_closing_my_reminder_does_not_close_the_task(self):
        self.Work.with_user(self.approver).assign('ei.contract', self.contract.id, self.approver2.id)
        mine = self.item(self.approver2, self.contract)['my_activity']
        with self.assertRaises(AccessError):
            self.Work.with_user(self.approver).done(mine)                 # not their reminder
        self.Work.with_user(self.approver2).done(mine)
        self.assertEqual(self.env['mail.activity'].search_count([('res_model', '=', 'ei.contract'), ('res_id', '=', self.contract.id)]), 0)
        self.assertTrue(self.item(self.approver2, self.contract), 'the contract still waits for its real approval')

    def test_18_escalation_needs_a_reason_and_tells_the_managers(self):
        W = self.Work.with_user(self.approver)
        with self.assertRaises(UserError):
            W.escalate('ei.contract', self.contract.id, 'x')
        res = W.escalate('ei.contract', self.contract.id, 'supplier is waiting at the gate')
        self.assertIn(self.ceo.name, res['managers'])
        act = self.env['mail.activity'].search([('res_model', '=', 'ei.contract'), ('res_id', '=', self.contract.id), ('user_id', '=', self.ceo.id)])
        self.assertTrue(act and act.summary.startswith('Escalated:'))
        t = self.item(self.approver, self.contract)
        self.assertEqual(t['status'], 'escalated')
        self.assertFalse(t['can_escalate'], 'it cannot be escalated twice')
        mine = self.item(self.ceo, self.contract)
        self.assertTrue(mine and mine['status'] == 'escalated' and mine['my_activity'], 'an escalated item always reaches the manager it was escalated to')
        self.assertIn('Escalated to management', ' '.join(self.contract.message_ids.mapped('body')))

    def test_19_many_old_codes_collapse_into_one_line(self):
        self.env['ei.import.batch'].with_user(self.importer).import_file('EXI_legacy_codes.csv', source_bytes())
        d = self.tasks(self.mapper)
        bulk = [t for t in d['items'] if t.get('bulk')]
        self.assertEqual(len(bulk), 1, 'one line, not hundreds of near-identical tasks')
        self.assertIn('old codes', bulk[0]['title'])
        self.assertEqual(bulk[0]['res_id'], 0)
        act = self.Work.with_user(self.mapper).open_task('ei.legacy.code', 0)
        self.assertEqual(act['res_model'], 'ei.legacy.code')
        self.assertTrue(act['views'] and act['domain'])
        self.assertEqual([t for t in self.tasks(self.ceo)['items'] if t.get('bulk')], [], 'oversight roles do not see the bulk to-do')

    def test_20_every_work_type_points_at_a_real_model_and_group(self):
        for spec in WORK:
            self.assertIn(spec['model'], self.env, spec['key'])
            for g in spec['groups']:
                self.env.ref(g)
            self.assertTrue(spec['verb'] and spec['next'] and spec['step'])
            self.env[spec['model']].search_count(spec['domain'])

    def test_21_every_work_model_can_be_assigned_and_no_stray_models_exist(self):
        """Regression: extending a model with a mixin without `_name` silently created seven new models instead."""
        for spec in WORK:
            self.assertIn('activity_ids', self.env[spec['model']]._fields, '%s cannot be assigned or escalated' % spec['key'])
        self.assertEqual([m for m in self.env.registry if m.startswith('ei.') and m.endswith('.activity')], [])

    # ------------------------------------------------------------------ search
    def test_30_search_finds_what_the_user_may_read_and_nothing_else(self):
        S = self.env['ei.search']
        hit = S.with_user(self.approver).search('V2-A')
        self.assertEqual([g['label'] for g in hit['groups']], ['Contracts'])
        self.assertEqual(hit['groups'][0]['hits'][0]['res_id'], self.contract.id)
        self.assertEqual(S.with_user(self.cash).search('V2-A')['total'], 0, 'a cash clerk cannot read contracts, so cannot find them')
        self.assertEqual(S.with_user(self.approver).search('a')['total'], 0, 'one letter is too short')
        self.assertEqual(S.with_user(self.approver).search('%%')['total'], 0, 'wildcards are literal')
        self.assertEqual(S.with_user(self.approver).search('V2_A')['total'], 0, '_ is literal too')

    def test_31_old_codes_are_matched_as_text_and_parties_come_first(self):
        self.env['ei.import.batch'].with_user(self.importer).import_file('EXI_legacy_codes.csv', source_bytes())
        S = self.env['ei.search'].with_user(self.mapper)
        res = S.search('4.20')
        self.assertTrue(any(h['title'].startswith('4.20 ') for g in res['groups'] for h in g['hits']))
        self.assertEqual(S.search('4.2')['total'] >= 1, True)
        self.assertFalse(any(h['title'].startswith('4.2 ') for g in S.search('4.2')['groups'] for h in g['hits']), '4.2 is not 4.20')
        parties = S.parties('V2', limit=12)
        flags = [bool(p['partner_id']) for p in parties]
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_32_a_hit_opens_only_an_allowed_record_the_user_may_read(self):
        S = self.env['ei.search']
        self.assertEqual(S.with_user(self.approver).open('ei.contract', self.contract.id)['res_id'], self.contract.id)
        self.assertEqual(S.with_user(self.approver).open('ei.party360', self.parent.id)['tag'], 'ei_party360')
        with self.assertRaises(AccessError):
            S.with_user(self.cash).open('ei.contract', self.contract.id)
        with self.assertRaises(AccessError):
            S.with_user(self.approver).open('res.users', 1)

    # ------------------------------------------------------------------ the rest
    def test_40_activity_feed_shows_only_readable_records(self):
        feed = self.home(self.ceo)['activity']
        self.assertTrue(any(self.contract.display_name == a['what'] for a in feed) or feed)
        self.assertEqual([a for a in self.home(self.cash)['activity'] if a['model'] == 'ei.contract'], [])
        for a in feed:
            self.assertNotIn('*', a['text'])

    def test_40b_bulk_imports_do_not_flood_the_feed(self):
        self.env['ei.import.batch'].with_user(self.importer).import_file('EXI_legacy_codes.csv', source_bytes())
        feed = self.home(self.mapper)['activity']
        self.assertEqual([a for a in feed if a['model'] == 'ei.legacy.code'], [], '639 "code created" lines must not fill the feed')

    def test_41_header_counts_are_real(self):
        self.Work.with_user(self.approver).assign('ei.contract', self.contract.id, self.approver2.id)
        h = self.home(self.approver2)['header']
        self.assertEqual(h['reminders'], 1)
        self.assertGreaterEqual(h['approvals'], 1)
        self.assertEqual(h['role'], 'Contract desk')

    def test_42_plurals_read_naturally(self):
        from odoo.addons.ei_ui_theme.models.home import _n
        self.assertEqual(_n(1, '%s loading', '%s loadings'), '1 loading')
        self.assertEqual(_n(2, '%s loading', '%s loadings'), '2 loadings')
        self.assertEqual(_n(0, '%s loading', '%s loadings'), '0 loadings')

    def test_43_dark_theme_follows_the_viewers_cookie(self):
        http = self.env['ir.http']
        for cookie, want in (('dark', 'dark'), ('light', 'light'), (None, 'light'), ('weird', 'light')):
            req = SimpleNamespace(httprequest=SimpleNamespace(cookies={'color_scheme': cookie} if cookie else {}))
            with patch('odoo.addons.ei_ui_theme.models.ir_http.request', req):
                self.assertEqual(http.color_scheme(), want, cookie)

    def test_44_home_cost_grows_slowly_with_the_number_of_tasks(self):
        """Guard against a query-per-task loop: 20 more waiting contracts must add only a few queries each."""
        def cost():
            self.env.invalidate_all()
            n0 = self.cr.sql_log_count
            self.Home.with_user(self.approver).get_data()
            return self.cr.sql_log_count - n0
        base = cost()
        for i in range(20):
            self.reviewed_contract(self.maker, 'V2-BULK-%02d' % i)
        grown = cost()
        self.assertLess((grown - base) / 20.0, 8, 'Home got %s -> %s queries for 20 more tasks: look for an N+1' % (base, grown))
        self.assertLess(grown, 400)
