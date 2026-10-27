"""The four financial previews, their PDF and their scheduled delivery, on the same world the end-to-end journey builds (real role users, real
posted records, no mocks). The figures must agree with the management summary and with the ledger itself, and the four checks on the page
must say "agrees" when the books do."""
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.ei_management_dashboard.tests.test_journey import TestJourney

EVER = '2000-01-01'


@tagged('post_install', '-at_install', 'ei')
class TestFinancials(TestJourney):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.supplier_bill = cls.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': cls.env['res.partner'].create({'name': 'Fin Supplier'}).id, 'invoice_date': cls.today,
            'invoice_line_ids': [Command.create({'name': 'transport', 'quantity': 1, 'price_unit': 4321, 'tax_ids': [Command.set([])]})]})
        cls.supplier_bill.action_post()
        cls.finance = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'f_finance', 'login': 'f_finance', 'email': 'f.finance@example.com',
            'group_ids': [Command.set([cls.env.ref('account.group_account_manager').id, cls.env.ref('ei_legacy_master.group_ei_user').id])]})
        cls.ceo.email = 'ceo@example.com'

    def fin(self, user=None):
        return self.env['ei.report.financials'].with_user(user or self.ceo)

    def everything(self, user=None):
        return self.fin(user).get_statements(EVER, str(self.today))

    # ------------------------------------------------------------------ figures
    def test_f01_result_agrees_with_the_management_summary(self):
        d = self.everything()
        dash = self.env['ei.dashboard'].with_user(self.ceo).create({'date_from': EVER, 'date_to': self.today})
        k = {x['key']: x['value'] for x in d['kpis']}
        self.assertAlmostEqual(k['revenue'], dash.revenue, places=2)
        self.assertAlmostEqual(k['costs'], dash.costs, places=2)
        self.assertAlmostEqual(d['pnl']['net'], dash.profit, places=2)
        self.assertGreater(k['revenue'], 0, 'the journey posts a customer invoice')
        self.assertGreaterEqual(k['costs'], 4321, 'the supplier bill is a cost')

    def test_f02_the_four_checks_agree_on_real_books(self):
        d = self.everything()
        self.assertEqual({c['key']: c['ok'] for c in d['checks']}, {'tb': True, 'bs': True, 'cf': True, 'pnl': True})
        bs = d['balance_sheet']
        self.assertAlmostEqual(bs['assets'], bs['liabilities_and_equity'], places=2)

    def test_f03_trial_balance_is_the_ledger(self):
        d = self.fin().get_statements(str(self.today.replace(day=1)), str(self.today))
        self.env.cr.execute("""SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0) FROM account_move_line
                                WHERE parent_state = 'posted' AND company_id = %s AND date >= %s AND date <= %s""",
                            [self.env.company.id, self.today.replace(day=1), self.today])
        debit, credit = self.env.cr.fetchone()
        self.assertAlmostEqual(d['trial_balance']['debit'], debit, places=2)
        self.assertAlmostEqual(d['trial_balance']['credit'], credit, places=2)
        self.assertAlmostEqual(d['trial_balance']['debit'], d['trial_balance']['credit'], places=2)

    def test_f04_cash_flow_runs_from_opening_to_closing(self):
        cf = self.everything()['cash_flow']
        self.assertAlmostEqual(cf['opening'] + cf['inflow'] - cf['outflow'], cf['closing'], places=2)
        self.assertGreater(next(r for r in cf['rows'] if r['key'] == 'customers')['inflow'], 0, 'the journey invoice was paid into the bank')

    def test_f05_a_row_opens_exactly_the_items_behind_it(self):
        d = self.everything()
        row = next(r for s in d['pnl']['sections'] if s['key'] == 'income' for r in s['rows'])
        act = self.fin().open_lines(row['account_id'], EVER, str(self.today))
        lines = self.env['account.move.line'].with_user(self.ceo).search(act['domain'])
        self.assertTrue(lines)
        self.assertAlmostEqual(-sum(lines.mapped('balance')), row['amount'], places=2)
        self.assertEqual(set(lines.mapped('parent_state')), {'posted'})
        with self.assertRaises(UserError):
            self.fin().open_lines(0)

    def test_f06_a_period_that_ends_before_it_starts_is_refused(self):
        with self.assertRaises(UserError):
            self.fin().get_statements(str(self.today), '2001-01-01')
        self.assertEqual([c['key'] for c in self.fin().period_choices()], ['month', 'last_month', 'quarter', 'year', 'all'])

    # ------------------------------------------------------------------ who
    def test_f07_only_finance_management_and_the_auditor(self):
        for user in (self.ceo, self.finance):
            self.assertTrue(self.everything(user)['kpis'], user.login)
        for user in (self.dispatch, self.maker, self.cashclerk, self.officer, self.auditor):         # the auditor cannot read journal items (open decision 29)
            with self.assertRaises(AccessError, msg=user.login):
                self.everything(user)
        cat = {e['key']: e for e in self.env['ei.report.catalog'].with_user(self.ceo).get_catalog()}
        for key in ('pnl', 'balance_sheet', 'trial_balance', 'cash_flow'):
            self.assertEqual(cat[key]['status'], 'preview', key)                     # labelled preview, never "delivered"
            self.assertTrue(cat[key]['can_open'], key)
            self.assertIn('Preview', cat[key]['note'])
        ops = {e['key']: e for e in self.env['ei.report.catalog'].with_user(self.dispatch).get_catalog()}
        self.assertFalse(ops['pnl']['can_open'])

    # ------------------------------------------------------------------ the PDF
    def test_f08_the_printed_statement_carries_the_preview_label(self):
        R = self.env['ir.actions.report'].with_user(self.ceo)
        html, _kind = R._render_qweb_html('ei_reports.report_financial', None, data={'statement': 'summary', 'date_from': EVER, 'date_to': str(self.today)})
        html = html.decode()
        self.assertIn('(PREVIEW)', html)
        for title in ('Profit and loss', 'Balance sheet', 'Trial balance', 'Cash flow', 'Checks'):
            self.assertIn(title, html)
        self.assertNotIn('DOES NOT AGREE', html)
        with self.assertRaises(AccessError):
            self.env['ir.actions.report'].with_user(self.dispatch)._render_qweb_html('ei_reports.report_financial', None, data={'statement': 'pnl'})
        # the real PDF (wkhtmltopdf fetches the styles from a running server) is checked by the browser suite, which downloads it

    # ------------------------------------------------------------------ scheduled delivery
    def schedule(self, **kw):
        return self.env['ei.report.schedule'].with_user(self.ceo).create(dict({'name': 'Monthly P&L', 'statement': 'pnl', 'recipient_ids': [Command.set([self.ceo.id, self.finance.id])]}, **kw))

    def test_s01_a_schedule_starts_off_and_only_management_switches_it_on(self):
        s = self.schedule(enabled=True)
        self.assertFalse(s.enabled, 'a new schedule is off whatever the caller asked')
        with self.assertRaises(UserError):
            s.write({'enabled': True})                                                   # never by writing the field
        with self.assertRaises(AccessError):
            s.with_user(self.finance).action_switch_on()                                 # finance prepares, management switches on
        s.action_switch_on()
        self.assertTrue(s.enabled and s.next_run and s.switched_on_by_id == self.ceo)
        with self.assertRaises(UserError):
            s.write({'recipient_ids': [Command.set([self.ceo.id])]})                     # what was agreed is what runs
        s.action_switch_off()
        self.assertFalse(s.enabled or s.next_run)

    def test_s02_never_to_someone_who_may_not_see_it_or_outside(self):
        with self.assertRaises(UserError):
            self.schedule(recipient_ids=[Command.set([self.dispatch.id])])
        portal = self.env['res.users'].with_context(no_reset_password=True).create({'name': 'Outside', 'login': 'f_outside', 'group_ids': [Command.set([self.env.ref('base.group_portal').id])]})
        with self.assertRaises(UserError):
            self.schedule(recipient_ids=[Command.set([portal.id])])
        with self.assertRaises(UserError):
            self.schedule(recipient_ids=[]).action_switch_on()                           # nobody chosen yet

    def test_s03_a_test_goes_only_to_the_person_who_presses_it_and_is_logged(self):
        s = self.schedule()
        s.action_send_test()
        run = s.run_ids
        self.assertEqual(len(run), 1)
        self.assertTrue(run.test)
        self.assertEqual(run.recipients, self.ceo.name)
        self.assertIn(run.status, ('sent', 'queued'))
        self.assertTrue(run.attachment_id and run.attachment_id.name.endswith('-PREVIEW.pdf'))
        mails = self.env['mail.mail'].sudo().search([('attachment_ids', 'in', run.attachment_id.ids)])
        self.assertEqual(mails.mapped('email_to'), ['ceo@example.com'])
        self.assertIn('Preview', mails.body_html)
        with self.assertRaises(AccessError):
            s.with_user(self.dispatch).action_send_test()

    def test_s04_the_daily_run_sends_what_is_due_and_nothing_that_is_off(self):
        on, off = self.schedule(name='on'), self.schedule(name='off')
        on.action_switch_on()
        on.sudo().write({'next_run': self.today})
        self.env['ei.report.schedule']._cron_run_due()
        self.assertEqual(len(on.run_ids), 1)
        self.assertFalse(on.run_ids.test)
        self.assertEqual(set(on.run_ids.recipients.split(', ')), {self.ceo.name, self.finance.name})
        self.assertGreater(on.next_run, self.today)
        self.assertFalse(off.run_ids, 'a schedule that is off never sends')
        self.env['ei.report.schedule']._cron_run_due()
        self.assertEqual(len(on.run_ids), 1, 'not twice for the same day')

    def test_s05_someone_without_an_email_address_is_skipped_and_said_so(self):
        self.finance.email = False
        s = self.schedule()
        s.action_switch_on()
        s.sudo().write({'next_run': self.today})
        self.env['ei.report.schedule']._cron_run_due()
        self.assertIn(self.finance.name, s.run_ids.message)
        self.assertIn('Not sent to', s.run_ids.message)
