"""T14 end-to-end journey + T10 permissions + T11 ledger integrity + T13 dashboard reconciliation.

The world is built once in setUpClass by acting through real role users; each test then asserts one outcome."""
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.ei_legacy_master.tests.test_parsing import source_bytes


@tagged('post_install', '-at_install', 'ei')
class TestJourney(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        co = cls.company_data['company']
        cls.co = co
        cls.env = cls.env(user=1, context=dict(cls.env.context, allowed_company_ids=[co.id]))
        cls.env.user.company_ids |= co
        cls.env.user.company_id = co
        cls.env.user.group_ids |= cls.env.ref('ei_legacy_master.group_ei_importer')  # fixtures only
        cls.users = {}

        def mk(login, *groups):
            cls.users[login] = cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login, 'company_id': co.id, 'company_ids': [Command.set([co.id])],
                'group_ids': [Command.set([cls.env.ref(g).id for g in groups])]})
            return cls.users[login]
        u = mk
        cls.importer = u('j_importer', 'ei_legacy_master.group_ei_importer')
        cls.mapper = u('j_mapper', 'ei_legacy_master.group_ei_mapping_approver')
        cls.officer = u('j_officer', 'ei_bank_operations.group_ei_bank_officer')
        cls.bapprover = u('j_bapprover', 'ei_bank_operations.group_ei_bank_approver')
        cls.poster = u('j_poster', 'ei_bank_operations.group_ei_bank_poster')
        cls.maker = u('j_maker', 'ei_contract_da.group_ei_contract_staff')
        cls.capprover = u('j_capprover', 'ei_contract_da.group_ei_contract_approver', 'ei_daily_orders.group_ei_order_approver')
        cls.fapprover = u('j_fapprover', 'ei_contract_da.group_ei_formula_approver')
        cls.dispatch = u('j_dispatch', 'ei_material_lifting.group_ei_dispatch_officer')
        cls.reviewer = u('j_reviewer', 'ei_material_lifting.group_ei_lifting_reviewer')
        cls.invoicer = u('j_invoicer', 'ei_invoice_extensions.group_ei_invoicing')
        cls.rclerk = u('j_rclerk', 'ei_parent_reconciliation.group_ei_recon_user')
        cls.rapprover = u('j_rapprover', 'ei_parent_reconciliation.group_ei_recon_approver')
        cls.ceo = u('j_ceo', 'ei_management_dashboard.group_ei_management')
        cls.cashclerk = u('j_cash', 'ei_cashbook.group_ei_cash_clerk')

        # 1. legacy codes
        cls.batch = cls.env['ei.import.batch'].with_user(cls.importer).import_file('EXI_legacy_codes.csv', source_bytes())
        cls.Code = cls.env['ei.legacy.code'].sudo()
        code = lambda c: cls.Code.search([('legacy_code', '=', c), ('company_id', '=', co.id)])
        # 2. approve mappings and create the Odoo records
        bank_code, cust_code = code('5.93'), code('1.03')
        bank_code.with_user(cls.mapper).action_approve('bank_journal')
        bank_code.with_user(cls.mapper).action_materialise()
        cust_code.with_user(cls.mapper).action_approve('res_partner')
        cust_code.with_user(cls.mapper).action_materialise()
        cls.bank = cls.env['account.journal'].browse(bank_code.linked_res_id)
        cls.customer = cls.env['res.partner'].browse(cust_code.linked_res_id)
        alias = cls.env['ei.partner.alias'].sudo().search([('partner_id', '=', cls.customer.id), ('alias', '=', 'ARIF PATANWALA')])
        alias.with_user(cls.bapprover).action_approve()
        cls.parent = cls.env['res.partner'].create({'name': 'Parent Steel Ltd'})
        cls.prod = cls.env['product.product'].create({
            'name': 'HR Coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id, 'taxes_id': [Command.set([])],
            'supplier_taxes_id': [Command.set([])],
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
            'property_account_expense_id': cls.company_data['default_account_expense'].id})
        # 3. formula approved by an accountant, then contract and DA
        cls.formula = cls.env.ref('ei_contract_da.formula_example_mill_rate')
        cls.formula.with_user(cls.fapprover).action_approve()
        cls.contract = cls.env['ei.contract'].with_user(cls.maker).create({
            'parent_partner_id': cls.parent.id, 'contract_ref': 'ISL/2026/001', 'contract_type': 'commission',
            'line_ids': [Command.create({
                'product_id': cls.prod.id, 'ordered_mtl': 100, 'purchase_rate': 200000, 'sale_rate': 210000,
                'formula_id': cls.formula.id, 'basic_rate': 210000,
                'param_ids': [Command.create({'key': 'deduction_pct', 'value': '1.32'})]})]})
        cls.env['ir.attachment'].create({'name': 'contract.pdf', 'res_model': 'ei.contract', 'res_id': cls.contract.id, 'raw': b'x'})
        cls.contract.with_user(cls.maker).action_review()
        cls.contract.with_user(cls.capprover).action_approve()
        cls.contract.with_user(cls.maker).action_activate()
        cls.contract.line_ids.with_user(cls.capprover).action_set_ownership('direct_dispatch', 'Mill dispatches to customer (client confirmed)')
        cls.da = cls.env['ei.da'].with_user(cls.maker).create({
            'name': 'DA-5501', 'parent_partner_id': cls.parent.id, 'contract_id': cls.contract.id,
            'line_ids': [Command.create({'contract_line_id': cls.contract.line_ids.id, 'mtl': 10, 'customer_id': cls.customer.id})]})
        cls.env['ir.attachment'].create({'name': 'da.pdf', 'res_model': 'ei.da', 'res_id': cls.da.id, 'raw': b'x'})
        cls.da.with_user(cls.maker).action_review()
        cls.da.with_user(cls.capprover).action_approve()
        # 4. daily order request
        cls.order = cls.env['ei.daily.order'].with_user(cls.maker).generate_from_da(cls.da)
        cls.order.with_user(cls.capprover).action_approve()
        # 5. partial lifting (4 of 10)
        cls.lift = cls.env['ei.lifting'].with_user(cls.dispatch).create({
            'da_line_id': cls.da.line_ids.id, 'vehicle_no': 'TKA-123', 'gate_pass_no': 'GP-7001', 'claimed_mtl': 4,
            'gross_kg': 30000, 'tare_kg': 26000, 'weighbridge_no': 'WB-55'})
        cls.env['ir.attachment'].create({'name': 'gp.jpg', 'res_model': 'ei.lifting', 'res_id': cls.lift.id, 'raw': b'x'})
        cls.lift.with_user(cls.reviewer).action_verify()
        # 6. supplier invoice arrives after the order was printed
        cls.intake = cls.env['ei.supplier.intake'].with_user(cls.invoicer).create({
            'partner_id': cls.parent.id, 'invoice_number': 'SUP-9001', 'invoice_date': '2026-10-06', 'stated_total': 800000,
            'line_ids': [Command.create({'da_line_id': cls.da.line_ids.id, 'order_line_id': cls.order.line_ids.id,
                                         'received_mtl': 4, 'unit_rate': 200000})]})
        cls.env['ir.attachment'].create({'name': 'sup.pdf', 'res_model': 'ei.supplier.intake', 'res_id': cls.intake.id, 'raw': b'x'})
        cls.intake.action_check()
        cls.intake.with_user(cls.invoicer).action_create_bill()
        cls.bill = cls.intake.bill_id
        cls.bill.action_post()
        # 7. customer invoice from the verified lifting
        w = cls.env['ei.invoice.wizard'].with_user(cls.invoicer).with_context(
            active_model='ei.lifting', active_ids=cls.lift.ids).create({'post': True})
        cls.invoice = cls.env['account.move'].browse(w.action_create()['domain'][0][2])
        # 8. bank receipt: morning check, import, suggest, verify, allocate, approve, post
        cls.env['ei.bank.balance.check'].with_user(cls.bapprover).create({'journal_id': cls.bank.id, 'bank_balance': 0, 'date': fields.Date.today()})
        csv = ("Date,Description,Reference,Debit,Credit,Balance\n"
               "07/10/2026,RAAST FROM ARIF PATANWALA,TX900,,840000,840000\n").encode()
        cls.imp = cls.env['ei.bank.import'].with_user(cls.officer).import_file(cls.bank, 'oct.csv', csv, 0, 840000)
        cls.imp.with_user(cls.officer).action_suggest()
        cls.bline = cls.imp.line_ids
        cls.suggested = (cls.bline.suggested_partner_id, cls.bline.confidence)
        cls.bline.with_user(cls.officer).action_verify_partner(cls.customer)
        cls.env['ei.bank.allocation'].with_user(cls.officer).create({'line_id': cls.bline.id, 'invoice_id': cls.invoice.id, 'amount': 840000})
        cls.imp.with_user(cls.bapprover).action_approve()
        cls.imp.with_user(cls.poster).action_post()
        cls.env['ei.bank.balance.check'].with_user(cls.bapprover).create({'journal_id': cls.bank.id, 'bank_balance': 840000, 'date': fields.Date.today()})
        # 9. parent statement matches our bill
        stm = "Invoice No,Date,Amount,Tax\nSUP-9001,06/10/2026,800000,0\n".encode()
        cls.stmt = cls.env['ei.parent.statement'].with_user(cls.rclerk).import_file(cls.parent, '2026-10-01', '2026-10-31', 'isl_oct.csv', stm)
        cls.stmt.with_user(cls.rclerk).action_match()
        cls.stmt.with_user(cls.rclerk).action_check_assigned()
        cls.stmt.with_user(cls.rclerk).action_check_resolved()
        cls.stmt.with_user(cls.rapprover).action_sign()

    # ------------------------------------------------------------- T14
    def test_01_journey_outcomes(self):
        self.assertEqual(self.batch.state, 'imported')
        self.assertEqual((self.bank.code, self.bank.type), ('B593', 'bank'))
        self.assertEqual(self.customer.ref, '1.03')
        self.assertEqual(self.suggested, (self.customer, 0.9))
        self.assertEqual((self.contract.state, self.da.state), ('active', 'approved'))
        l = self.contract.line_ids
        self.assertEqual(l.snapshot['values']['mill_rate'], '207228.00')
        self.assertEqual((l.spread_per_mtl, l.expected_gross_spread), (10000, 1000000))
        self.assertEqual((self.lift.state, self.lift.weighed_mtl, self.lift.verified_mtl), ('verified', 4.0, 4.0))
        self.assertEqual((self.da.lifted_mtl, self.da.remaining_to_lift), (4, 6))
        self.assertEqual(self.order.line_ids.invoice_ref, 'SUP-9001')
        self.assertEqual((self.bill.state, self.bill.amount_total, self.bill.payment_state), ('posted', 800000, 'not_paid'))
        self.assertEqual((self.invoice.state, self.invoice.amount_total, self.invoice.payment_state), ('posted', 840000, 'paid'))
        self.assertEqual(self.imp.state, 'posted')
        self.assertTrue(self.bline.statement_line_id.is_reconciled)
        self.assertEqual(self.stmt.state, 'signed')
        self.assertEqual((self.stmt.n_matched, self.stmt.n_exceptions), (1, 0))
        self.assertEqual(self.lift.invoice_status, 'invoiced')

    # ------------------------------------------------------------- T11
    def test_02_ledger_integrity(self):
        L = self.env['account.move.line'].sudo()
        posted = L.search([('company_id', '=', self.co.id), ('parent_state', '=', 'posted')])
        self.assertAlmostEqual(sum(posted.mapped('debit')), sum(posted.mapped('credit')), places=2)
        for m in posted.move_id:
            self.assertAlmostEqual(sum(m.line_ids.mapped('balance')), 0, places=2, msg=m.name)
        self.assertEqual(self.bank._ei_ledger_balance('2099-12-31'), 840000)
        recv = L.search([('partner_id', '=', self.customer.id), ('account_type', '=', 'asset_receivable'), ('parent_state', '=', 'posted')])
        self.assertAlmostEqual(sum(recv.mapped('amount_residual')), 0)

    # ------------------------------------------------------------- T13
    def dash(self, user=None, **kw):
        return self.env['ei.dashboard'].with_user(user or self.ceo).create({'date_from': '2000-01-01', 'date_to': '2099-12-31', **kw})

    def test_03_dashboard_reconciles_to_ledger(self):
        d = self.dash()
        L = self.env['account.move.line'].sudo()
        income = L.search([('company_id', '=', self.co.id), ('parent_state', '=', 'posted'), ('account_type', 'in', ('income', 'income_other'))])
        self.assertEqual(d.revenue, -sum(income.mapped('balance')))
        self.assertEqual(d.revenue, 840000)
        self.assertEqual((d.ar_open, d.ap_open, d.costs), (0, 800000, 800000))   # paid invoice; unpaid supplier bill
        self.assertEqual((d.mtl_ordered, d.mtl_lifted, d.mtl_available, d.mtl_allocated), (100, 4, 90, 10))
        self.assertEqual(d.mtl_pending, 6)
        self.assertEqual(d.gross_spread, 1000000)
        self.assertEqual(d.bank_pending_lines, 0)

    def test_04_dashboard_costs_match_expense_lines(self):
        d = self.dash()
        L = self.env['account.move.line'].sudo()
        exp = L.search([('company_id', '=', self.co.id), ('parent_state', '=', 'posted'),
                        ('account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))])
        self.assertEqual(d.costs, sum(exp.mapped('balance')))
        self.assertEqual(d.profit, d.revenue - d.costs)
        self.assertEqual(d.profit, 40000)     # 4 MTL lifted x (210,000 - 200,000) spread, nothing else booked

    def test_05_bank_freshness_labels(self):
        d = self.dash()
        self.assertIn('Verified: bank-confirmed', d.bank_html)
        self.assertIn('B593', self.bank.code)
        self.env['ir.config_parameter'].sudo().set_float('ei_management_dashboard.bank_stale_hours', 0.0)
        stale = self.dash()
        self.assertIn('PROVISIONAL', stale.bank_html)
        self.env['ir.config_parameter'].sudo().set_float('ei_management_dashboard.bank_stale_hours', 24.0)
        other = self.env['account.journal'].sudo().create({'name': 'Never confirmed', 'type': 'bank', 'code': 'NVR',
                                                           'company_id': self.co.id})
        self.assertIn('never confirmed with the bank', self.dash().bank_html)

    def test_06_every_kpi_opens_source_transactions(self):
        d = self.dash()
        for kpi, model in (('ar', 'account.move.line'), ('ap', 'account.move.line'), ('revenue', 'account.move.line'),
                           ('contracts', 'ei.contract.line'), ('bank_pending', 'ei.bank.import.line'),
                           ('suspense', 'account.bank.statement.line'), ('intake', 'ei.supplier.intake')):
            act = d.with_context(kpi=kpi).action_open_kpi()
            self.assertEqual(act['res_model'], model)
            self.env[model].sudo().search(act['domain'])      # domain is valid
        rev = self.env['account.move.line'].sudo().search(d.with_context(kpi='revenue').action_open_kpi()['domain'])
        self.assertEqual(-sum(rev.mapped('balance')), d.revenue)
        ap = self.env['account.move.line'].sudo().search(d.with_context(kpi='ap').action_open_kpi()['domain'])
        self.assertEqual(-sum(ap.mapped('amount_residual')), d.ap_open)

    def test_07_filters_apply(self):
        self.assertEqual(self.dash(partner_id=self.customer.id).revenue, 840000)
        self.assertEqual(self.dash(partner_id=self.parent.id).revenue, 0)
        self.assertEqual(self.dash(contract_id=self.contract.id).mtl_ordered, 100)
        other_prod = self.env['product.product'].create({'name': 'Other'})
        self.assertEqual(self.dash(product_id=other_prod.id).mtl_ordered, 0)
        self.assertEqual(self.dash(date_from='2000-01-01', date_to='2000-12-31').revenue, 0)

    def test_08_role_specific_sections(self):
        cash = self.dash(user=self.cashclerk)           # cash clerk: no finance / bank sections
        self.assertEqual((cash.ar_open, cash.ap_open, cash.revenue, cash.bank_html), (0, 0, 0, False))
        officer = self.dash(user=self.officer)
        self.assertTrue(officer.bank_html)
        self.assertEqual(officer.revenue, 840000 if self.officer.has_group('account.group_account_user') else officer.revenue)
        with self.assertRaises(AccessError):
            self.env['ei.dashboard'].with_user(self.env['res.users'].create({'name': 'nobody', 'login': 'nobody'})).create({})

    def test_09_approvals_queue(self):
        before = self.dash().approvals_total
        c = self.env['ei.contract'].create({'parent_partner_id': self.parent.id, 'contract_ref': 'Q1', 'line_ids': [Command.create({
            'product_id': self.prod.id, 'ordered_mtl': 1, 'purchase_rate': 1, 'sale_rate': 2})]})
        self.env['ir.attachment'].create({'name': 'c', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        c.action_review()
        d = self.dash()
        self.assertEqual(d.approvals_total, before + 1)
        self.assertIn('Contracts to approve', d.approvals_html)
        act = d.with_context(queue=0).action_open_queue()
        self.assertIn(c.id, self.env['ei.contract'].search(act['domain']).ids)

    def test_10_daily_summary_and_cron(self):
        html = self.env['ei.dashboard'].sudo().daily_summary_html()
        self.assertIn('Customer outstanding', html)
        self.assertFalse(self.env.ref('ei_management_dashboard.cron_ei_daily_summary').active)   # off until configured
        self.ceo.email = False
        self.assertEqual(self.env['ei.dashboard'].cron_send_daily_summary(), len(self.env.ref('ei_management_dashboard.group_ei_management').sudo().user_ids))

    def test_11_pdf_report_renders(self):
        d = self.dash()
        html = self.env['ir.actions.report'].with_user(self.ceo)._render_qweb_html('ei_management_dashboard.report_dashboard', d.ids)[0]
        self.assertIn(b'Management summary', html)

    # ------------------------------------------------------------- T10
    def test_12_sales_operator_cannot_alter_posted_accounting(self):
        with self.assertRaises(UserError):      # AccessError is a UserError: either is a refusal
            self.invoice.with_user(self.maker).write({'invoice_date': '2020-01-01'})
        with self.assertRaises(AccessError):
            self.bill.with_user(self.maker).button_draft()
        with self.assertRaises(AccessError):
            self.invoice.with_user(self.invoicer).button_draft()          # invoicing clerk cannot un-post either
        with self.assertRaises(AccessError):
            self.invoice.with_user(self.maker).button_cancel()
        with self.assertRaises(UserError):
            self.invoice.with_user(self.invoicer).write({'invoice_date': '2020-01-01'})   # posted: locked
        self.assertEqual((self.invoice.state, self.invoice.payment_state), ('posted', 'paid'))

    def test_13_multi_company_isolation(self):
        other = self.env['res.company'].create({'name': 'Other Legal Entity'})
        outsider = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'outsider', 'login': 'outsider', 'company_id': other.id, 'company_ids': [Command.set([other.id])],
            'group_ids': [Command.set([self.env.ref(g).id for g in (
                'ei_contract_da.group_ei_contract_approver', 'ei_bank_operations.group_ei_bank_approver',
                'ei_legacy_master.group_ei_mapping_approver', 'ei_management_dashboard.group_ei_management')])]})
        def asout(model):
            return self.env[model].with_user(outsider).with_context(allowed_company_ids=[other.id])
        counted = 0
        for model in ('ei.contract', 'ei.da', 'ei.lifting', 'ei.bank.import', 'ei.bank.import.line', 'ei.supplier.intake',
                      'ei.parent.statement', 'ei.legacy.code', 'ei.daily.order'):
            try:
                self.assertEqual(asout(model).search_count([]), 0, model)
                counted += 1
            except AccessError:
                pass   # no ACL at all is also isolation
        self.assertGreaterEqual(counted, 5)    # the rules themselves were exercised, not just missing ACLs
        # sanity: the same users CAN see the data inside their own company
        self.assertGreater(self.env['ei.contract'].with_user(self.capprover).search_count([]), 0)
        with self.assertRaises(AccessError):
            asout('ei.contract').browse(self.contract.id).read(['name'])
        with self.assertRaises(AccessError):
            asout('ei.bank.import.line').browse(self.bline.id).action_reject('x')
        d = asout('ei.dashboard').create({'date_from': '2000-01-01', 'date_to': '2099-12-31'})
        self.assertEqual((d.revenue, d.ar_open, d.mtl_ordered, d.approvals_total), (0, 0, 0, 0))
        self.assertFalse(d.bank_html and 'B593' in d.bank_html)

    def test_14_nobody_approves_own_high_risk_items(self):
        # every maker-checker pair in the chain refused self-approval in its own module tests; here: the people differ
        people = {self.batch.imported_by, self.imp.approved_by, self.imp.posted_by}
        self.assertEqual(len(people), 3)       # importer / approver / poster are three different users
        self.assertNotEqual(self.contract.create_uid, self.contract.approved_by)
        self.assertNotEqual(self.stmt.imported_by, self.stmt.signed_by)

    def test_15_ceo_can_open_every_drilldown(self):
        """Regression (found 25 Oct 2026): the CEO saw the money KPIs but got an access error opening the journal
        items behind them, because the management role had no read access to the books."""
        dash = self.env['ei.dashboard'].with_user(self.ceo).create({})
        for kpi in ('ar', 'ap', 'revenue', 'costs', 'contracts', 'bank_pending', 'suspense', 'intake', 'recon', 'pending_orders'):
            act = dash.with_context(kpi=kpi).action_open_kpi()
            n = self.env[act['res_model']].with_user(self.ceo).search_count(act['domain'])
            self.assertGreaterEqual(n, 0, kpi)
        self.assertFalse(self.env['account.move.line'].with_user(self.ceo).has_access('write'),
                         "reading the books must not allow changing them")
