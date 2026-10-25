from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ei')
class TestEasyInterface(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([cls.env.ref(g).id for g in gs] or [cls.env.ref('base.group_user').id])]})
        cls.cash = mk('u_cash', 'ei_cashbook.group_ei_cash_clerk')
        cls.contract_mgr = mk('u_contract', 'ei_contract_da.group_ei_contract_approver')
        cls.ceo = mk('u_ceo', 'ei_management_dashboard.group_ei_management')
        cls.plain = mk('u_plain')   # internal user with no Export International role
        cls.Home = cls.env['ei.home']
        # a reviewed contract = one visible "waiting for approval" item
        prod = cls.env['product.product'].create({'name': 'UI test coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        parent = cls.env['res.partner'].create({'name': 'UI test parent'})
        c = cls.env['ei.contract'].create({'parent_partner_id': parent.id, 'contract_ref': 'UI-1', 'line_ids': [Command.create({
            'product_id': prod.id, 'ordered_mtl': 5, 'purchase_rate': 1, 'sale_rate': 2})]})
        cls.env['ir.attachment'].create({'name': 'c', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        c.action_review()
        cls.contract = c

    def keys(self, data):
        return {t['key']: t for a in data['areas'] for t in a['tasks']}

    # ------------------------------------------------------------ home data
    def test_01_tasks_match_real_counts(self):
        d = self.Home.with_user(self.contract_mgr).get_data()
        t = self.keys(d)
        self.assertEqual(t['contracts']['count'], self.env['ei.contract'].search_count([('state', '=', 'reviewed')]))
        self.assertGreaterEqual(t['contracts']['count'], 1)
        self.assertEqual(t['contracts']['tone'], 'warning')
        self.assertEqual(t['das']['tone'], 'ok')          # nothing waiting -> green "All done"
        self.assertGreaterEqual(d['attention'], 1)

    def test_02_sections_follow_the_users_role(self):
        d = self.Home.with_user(self.cash).get_data()
        t = self.keys(d)
        self.assertIn('vouchers', t)
        for hidden in ('bank_lines', 'contracts', 'intake', 'recon'):
            self.assertNotIn(hidden, t)
        self.assertEqual({q['key'] for q in d['quick']}, {'q_voucher'})
        self.assertEqual(d['money'], [])                  # no finance numbers for a cash clerk
        self.assertEqual(d['banks'], [])

    def test_03_user_without_a_role_sees_a_polite_empty_page(self):
        d = self.Home.with_user(self.plain).get_data()
        self.assertTrue(d['empty'])
        self.assertEqual((d['areas'], d['quick'], d['steps']), ([], [], []))

    def test_04_ceo_sees_money_and_banks_but_cannot_create_records(self):
        d = self.Home.with_user(self.ceo).get_data()
        self.assertEqual({m['key'] for m in d['money']}, {'ar', 'ap', 'cash', 'profit'})
        self.assertFalse(d['quick'])                      # reporting role: nothing to create
        self.assertIn('greeting', d)

    def test_05_home_is_read_only(self):
        before = [self.env[m].search_count([]) for m in ('ei.contract', 'ei.da', 'ei.bank.import', 'ei.cash.voucher', 'account.move')]
        self.Home.with_user(self.contract_mgr).get_data()
        self.Home.with_user(self.ceo).get_data()
        self.assertEqual(before, [self.env[m].search_count([]) for m in ('ei.contract', 'ei.da', 'ei.bank.import', 'ei.cash.voucher', 'account.move')])

    def test_06_day_steps(self):
        steps = {s['key']: s for s in self.Home.with_user(self.contract_mgr).get_data()['steps']}
        self.assertIn('s_da', steps)
        self.assertFalse(steps['s_da']['done'])           # nothing entered today
        self.assertNotIn('s_bank', steps)                 # a contract manager has no bank access

    # ------------------------------------------------------------ clicks
    def test_07_clicks_open_the_right_records(self):
        act = self.Home.with_user(self.contract_mgr).open_task('contracts')
        self.assertEqual((act['res_model'], act['type']), ('ei.contract', 'ir.actions.act_window'))
        self.assertIn(self.contract.id, self.env['ei.contract'].search(act['domain']).ids)
        self.assertEqual(act['views'][0], [False, 'kanban'])       # cards first
        self.assertFalse(self.Home.open_task('nope'))
        wiz = self.Home.with_user(self.contract_mgr).open_quick('q_contract')
        self.assertEqual((wiz['res_model'], wiz['views']), ('ei.contract', [[False, 'form']]))
        bank = self.Home.with_user(self.env.ref('base.user_admin')).open_quick('q_bank')
        self.assertEqual(bank['target'], 'new')

    def test_08_money_drilldown_requires_finance_access(self):
        with self.assertRaises(AccessError):
            self.Home.with_user(self.plain).open_money('ar')

    # ------------------------------------------------------------ wording and structure
    def test_09_plain_labels_are_served_to_the_screens(self):
        f = self.env['ei.legacy.code'].fields_get(['original_name', 'proposed_target_type', 'verification_status'])
        self.assertEqual(f['original_name']['string'], 'Name in old system')
        self.assertEqual(f['proposed_target_type']['string'], 'Suggested use')
        b = self.env['ei.bank.import'].fields_get(['n_lines', 'n_open'])
        self.assertEqual((b['n_lines']['string'], b['n_open']['string']), ('Payments in file', 'Still to check'))
        # no leftover technical label on any visible EI field
        bad = []
        for model in ('ei.contract', 'ei.da', 'ei.lifting', 'ei.cash.voucher', 'ei.supplier.intake', 'ei.parent.statement', 'ei.bank.import.line'):
            for name, spec in self.env[model].fields_get().items():
                if spec['string'] in (name.replace('_', ' ').title(),) and name not in ('name', 'date', 'state', 'amount', 'balance', 'notes', 'note', 'quantity', 'kind', 'sequence', 'active', 'currency_id', 'company_id', 'lot', 'remarks', 'status', 'source', 'message_ids', 'has_message', 'message_needaction', 'message_has_error', 'message_is_follower', 'message_follower_ids', 'message_partner_ids', 'message_attachment_count', 'activity_ids', 'message_has_sms_error', 'message_needaction_counter', 'message_has_error_counter', 'activity_state', 'activity_user_id', 'activity_type_id', 'activity_date_deadline', 'my_activity_date_deadline', 'activity_summary', 'activity_exception_decoration', 'activity_exception_icon', 'activity_calendar_event_id', 'activity_type_icon', 'write_date', 'create_date', 'write_uid', 'create_uid', 'id', 'display_name', 'message_main_attachment_id', 'message_attachment_count', 'access_url', 'website_message_ids'):
                    bad.append('%s.%s=%s' % (model, name, spec['string']))
        self.assertEqual(bad, [], 'technical labels left on screen')

    def test_10_short_top_menu_in_plain_words(self):
        root = self.env.ref('ei_legacy_master.menu_ei_root')
        names = [m.name for m in self.env['ir.ui.menu'].search([('parent_id', '=', root.id)], order='sequence')]
        self.assertEqual([n for n in names if n != 'Customers & Suppliers'], ['Home', 'Money', 'Orders & Trucks', 'Bills & Invoices', 'Month-end', 'Approvals', 'Setup'])
        parent_of = lambda xid: self.env.ref(xid).parent_id.name
        self.assertEqual(parent_of('ei_cashbook.menu_ei_cash_vouchers'), 'Money')
        self.assertEqual(parent_of('ei_material_lifting.menu_ei_lifting'), 'Orders & Trucks')
        self.assertEqual(parent_of('ei_invoice_extensions.menu_ei_supplier_bills'), 'Bills & Invoices')
        self.assertEqual(parent_of('ei_contract_da.menu_ei_formula'), 'Setup')
        self.assertEqual(parent_of('ei_trade_lc.menu_ei_trade_lc'), 'Setup')

    def test_11_every_empty_screen_explains_what_to_do(self):
        acts = self.env['ir.actions.act_window'].search([('res_model', '=like', 'ei.%')])
        missing = [a.name for a in acts if a.res_model not in ('ei.dashboard',) and not (a.help or '').strip()
                   and a.res_model not in ('ei.import.wizard', 'ei.bank.import.wizard', 'ei.bank.line.wizard', 'ei.legacy.code.approve.wizard',
                                           'ei.legacy.link.wizard', 'ei.reason.wizard', 'ei.cash.decision.wizard', 'ei.invoice.wizard',
                                           'ei.parent.import.wizard', 'ei.compliance.submission')]
        self.assertEqual(missing, [])

    def test_12_cards_are_defined_and_valid(self):
        for model in ('ei.bank.import', 'ei.cash.voucher', 'ei.contract', 'ei.da', 'ei.daily.order', 'ei.lifting',
                      'ei.supplier.intake', 'ei.parent.statement'):
            views = self.env[model].get_views([(False, 'kanban')])['views']
            self.assertIn('ei-card-body', views['kanban']['arch'], model)

    def test_13_every_form_has_a_what_to_do_now_banner(self):
        for model in ('ei.contract', 'ei.da', 'ei.daily.order', 'ei.lifting', 'ei.bank.import', 'ei.cash.voucher',
                      'ei.supplier.intake', 'ei.parent.statement', 'ei.legacy.code', 'ei.formula.definition', 'ei.trade.lc'):
            arch = self.env[model].get_views([(False, 'form')])['views']['form']['arch']
            self.assertIn('ei-next', arch, model)

    def test_14_new_staff_land_on_home_without_tutorial_pointers(self):
        for u in (self.cash, self.contract_mgr, self.ceo):
            self.assertEqual(u.action_id.id, self.env.ref('ei_ui_theme.action_ei_home').id)
            self.assertFalse(u.tour_enabled)
        self.assertFalse(self.plain.action_id)             # not an Export International user

    def test_15_window_actions_returned_from_python_carry_views(self):
        """Regression (found 25 Oct 2026): Odoo 20's web client fails with "Cannot read properties of undefined
        (reading 'map')" when Python returns an act_window with `view_mode` but no `views`. The server-side work
        succeeded and the user still saw an error dialog (amend, import wizards, invoice wizard, KPI drill-downs).
        Every window action built in our Python code must carry `views`."""
        import ast
        import os
        from odoo.modules import get_module_path
        offenders = []
        names = self.env['ir.module.module'].search([('name', '=like', 'ei\\_%'), ('state', '=', 'installed')]).mapped('name')
        for name in names:
            for folder, _dirs, files in os.walk(get_module_path(name)):
                if os.sep + 'tests' in folder:
                    continue
                for fname in files:
                    if not fname.endswith('.py'):
                        continue
                    path = os.path.join(folder, fname)
                    with open(path) as fh:
                        tree = ast.parse(fh.read())
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Dict):
                            keys = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
                            t = keys.get('type')
                            if isinstance(t, ast.Constant) and t.value == 'ir.actions.act_window' and 'views' not in keys:
                                offenders.append('%s:%s' % (os.path.relpath(path, get_module_path(name)), node.lineno))
        self.assertEqual(offenders, [], "window actions without `views` break in the Odoo 20 web client")
