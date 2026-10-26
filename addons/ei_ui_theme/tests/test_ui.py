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

    # ------------------------------------------------------------ home data
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
        self.assertEqual([n for n in names if n != 'Customers & Suppliers'], ['Home', 'Money', 'Orders & Trucks', 'Reports', 'Bills & Invoices', 'Month-end', 'Approvals', 'Setup'])
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
        succeeded and the user still saw an error dialog. Verified scope: standard buttons are normalised by Odoo's button
        controller and work; custom Owl screens that fetch an action with orm.call (the Home money tiles) crash. Every window
        action built in our Python code must carry `views`."""
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

    def test_16_every_reason_button_is_allowed_by_its_wizard(self):
        """Regression (found by the browser suite, 25 Oct 2026): "Cancel order request" and "Reverse lifting" opened the
        reason wizard, and Confirm always answered "Action not allowed" because the wizard's allow-list did not know them."""
        import ast
        wiz = self.env['ei.reason.wizard']
        offered = []
        for act in self.env['ir.actions.act_window'].search([('res_model', '=', 'ei.reason.wizard')]):
            ctx = ast.literal_eval(act.context or '{}')
            if ctx.get('default_res_model'):
                offered.append((ctx['default_res_model'], ctx['default_method']))
        self.assertGreaterEqual(len(offered), 5, offered)
        self.assertIn(('ei.daily.order', 'action_cancel'), offered)
        self.assertIn(('ei.lifting', 'action_reverse'), offered)
        for pair in offered:
            self.assertIn(pair, wiz._allowed(), '%s.%s is offered on a screen but the wizard would refuse it' % pair)

    def test_17_import_wizards_accept_what_the_screen_uploads(self):
        """Regression (found by the browser suite, 25 Oct 2026): in Odoo 20 an uploaded file comes back from a Binary field as a
        BinaryValue, not base64 text, so all three import wizards failed on screen ("Oops") while the tests, which call
        import_file() directly with bytes, kept passing. Drive each wizard the way the form does: assign the file, press Import."""
        import base64
        from odoo.addons.ei_legacy_master.tests.test_parsing import source_bytes
        mk = lambda login, *gs: self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([self.env.ref(g).id for g in gs])]})
        importer = mk('w_importer', 'ei_legacy_master.group_ei_importer')
        batch = self.env['ei.import.wizard'].with_user(importer).create({
            'file': base64.b64encode(source_bytes()).decode(), 'filename': 'EXI_legacy_codes.csv'}).action_import()
        self.assertEqual(batch['res_model'], 'ei.import.batch')
        self.assertEqual(self.env['ei.import.batch'].browse(batch['res_id']).total_rows, 639)
        recon = mk('w_recon', 'ei_parent_reconciliation.group_ei_recon_user')
        parent = self.env['res.partner'].create({'name': 'Wizard parent'})
        st = self.env['ei.parent.import.wizard'].with_user(recon).create({
            'partner_id': parent.id, 'date_from': '2026-10-01', 'date_to': '2026-10-31', 'filename': 'p.csv',
            'file': base64.b64encode(b'Invoice No,Date,Amount,Tax\nW-1,06/10/2026,1000,0\n').decode()}).action_import()
        self.assertEqual(st['res_model'], 'ei.parent.statement')
        self.assertTrue(self.env['ei.parent.statement'].browse(st['res_id']).line_ids)
        officer = mk('w_officer', 'ei_bank_operations.group_ei_bank_officer')
        journal = self.env['account.journal'].create({'name': 'Wizard bank', 'type': 'bank', 'code': 'WZB'})
        res = self.env['ei.bank.import.wizard'].with_user(officer).create({
            'journal_id': journal.id, 'filename': 'b.csv', 'opening_balance': 0, 'closing_balance': 1000,
            'file': base64.b64encode(b'Date,Description,Reference,Debit,Credit,Balance\n25/10/2026,RAAST FROM WIZ,WZ-1,,1000,1000\n').decode()}).action_import()
        self.assertEqual(res['res_model'], 'ei.bank.import')
        self.assertEqual(self.env['ei.bank.import'].browse(res['res_id']).line_ids.mapped('amount'), [1000.0])
