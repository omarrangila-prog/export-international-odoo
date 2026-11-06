"""Real-browser checks with Odoo's own test framework (HttpCase.browser_js), so they also run where this repository is deployed, on
whichever edition that is. Each person signs in with their own role. Any error in the browser console fails the check, so a screen that
hits an access error or a bundle that fails to load cannot pass. Synthetic data only. Skipped by Odoo when no Chrome is installed."""
from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingHttpCommon

PRELUDE = """
const waitFor = async (selector, ms = 30000) => {
    const start = Date.now();
    while (Date.now() - start < ms) {
        const found = document.querySelector(selector);
        if (found) { return found; }
        await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error('never appeared: ' + selector);
};
const must = (ok, message) => { if (!ok) { throw new Error(message); } };
const fits = () => must(document.documentElement.scrollWidth <= window.innerWidth + 1,
    `page is ${document.documentElement.scrollWidth}px wide on a ${window.innerWidth}px screen`);
const assetsLoaded = async () => {
    must(!window.__odooAssetError, 'a script bundle failed to load');
    const sheets = [...document.querySelectorAll('link[rel=stylesheet]')].filter((l) => l.media !== 'print');
    must(sheets.length, 'no stylesheet on the page');
    for (const link of sheets) {
        const res = await fetch(link.href);
        must(res.ok, 'stylesheet ' + link.href + ' answered ' + res.status);
        must(!(await res.text()).includes('css_error_message'), 'the stylesheet did not compile');
    }
};
const clickText = (scope, text) => {
    const button = [...document.querySelectorAll(scope + ' button')].find((b) => b.textContent.trim() === text);
    must(button, 'no button "' + text + '" in ' + scope);
    button.click();
};
"""
HOME = '/odoo/action-ei_ui_theme.action_ei_home'
APP_COLOUR = "document.querySelector('meta[name=theme-color]').content"


class EiBrowserCase(AccountTestInvoicingHttpCommon):

    @classmethod
    def person(cls, login, *groups):
        company = cls.company_data['company']
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': login, 'company_id': company.id, 'company_ids': [Command.set([company.id])],
            'group_ids': [Command.set([cls.env.ref(g).id for g in groups])]})

    def check(self, url, body, login=None, **kw):
        code = '(async () => {%s\n%s\nconsole.log("test successful");})().catch((e) => console.error("EI CHECK: " + e.message));' % (PRELUDE, body)
        self.browser_js(url, code, login=login, timeout=90, **kw)


@tagged('post_install', '-at_install', 'ei')
class TestBrowserDesktop(EiBrowserCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = cls.person
        cls.ceo = mk('b_ceo', 'ei_management_dashboard.group_ei_management')
        cls.accountant = mk('b_acct', 'account.group_account_user', 'ei_contract_da.group_ei_formula_approver')
        cls.finance = mk('b_fin', 'account.group_account_manager', 'ei_bank_operations.group_ei_bank_approver', 'ei_cashbook.group_ei_cash_approver')
        cls.maker = mk('b_maker', 'ei_contract_da.group_ei_contract_staff')
        cls.approver = mk('b_appr', 'ei_contract_da.group_ei_contract_approver')
        cls.officer = mk('b_bank', 'ei_bank_operations.group_ei_bank_officer')
        cls.clerk = mk('b_cash', 'ei_cashbook.group_ei_cash_clerk')
        cls.dispatch = mk('b_disp', 'ei_material_lifting.group_ei_dispatch_officer')
        cls.invoicer = mk('b_inv', 'ei_invoice_extensions.group_ei_invoicing')
        cls.recon = mk('b_rec', 'ei_parent_reconciliation.group_ei_recon_user')
        cls.auditor = mk('b_aud', 'ei_legacy_master.group_ei_auditor')
        cls.parent = cls.env['res.partner'].create({'name': 'Browser Parent Mill'})
        cls.customer = cls.env['res.partner'].create({'name': 'Browser Customer'})
        product = cls.env['product.product'].create({'name': 'Browser coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        Contract = cls.env['ei.contract'].with_user(cls.maker)

        def contract(ref):
            c = Contract.create({'parent_partner_id': cls.parent.id, 'contract_ref': ref, 'line_ids': [Command.create({
                'product_id': product.id, 'ordered_mtl': 10, 'purchase_rate': 200000, 'sale_rate': 210000})]})
            cls.env['ir.attachment'].sudo().create({'name': 'c.pdf', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'%PDF-1.4'})
            c.action_review()
            return c
        cls.waiting = contract('BROWSER-WAITING')
        cls.cancelled_look = contract('BROWSER-KEEP')
        active = contract('BROWSER-ACTIVE')
        active.with_user(cls.approver).action_approve()
        active.action_activate()
        da = cls.env['ei.da'].with_user(cls.maker).create({'name': 'BROWSER-DA', 'parent_partner_id': cls.parent.id, 'contract_id': active.id, 'line_ids': [
            Command.create({'contract_line_id': active.line_ids.id, 'mtl': 5, 'customer_id': cls.customer.id})]})
        cls.env['ir.attachment'].sudo().create({'name': 'd.pdf', 'res_model': 'ei.da', 'res_id': da.id, 'raw': b'%PDF-1.4'})
        da.action_review()
        da.with_user(cls.approver).action_approve()
        cls.intake = cls.env['ei.supplier.intake'].with_user(cls.invoicer).create({
            'partner_id': cls.parent.id, 'invoice_number': 'BROWSER-INV', 'invoice_date': '2026-10-05', 'stated_total': 400000,
            'line_ids': [Command.create({'da_line_id': da.line_ids.id, 'received_mtl': 2, 'unit_rate': 200000, 'hs_code': '7208.3990'})]})
        rows = 'Date,Description,Reference,Debit,Credit,Balance\n05/10/2026,RAAST FROM BROWSER PAYER,BROWSER-1,,1000,1000\n'.encode()
        cls.env['ei.bank.import'].with_user(cls.officer).import_file(cls.company_data['default_journal_bank'], 'browser.csv', rows, 0, 1000)

    def test_b01_sign_in_page_and_assets(self):
        self.check('/web/login', f"""
            await waitFor('input[name=login]');
            must({APP_COLOUR} === '#F4F6FA', 'theme colour is ' + {APP_COLOUR});
            must(document.querySelector('link[rel=manifest]'), 'no app manifest');
            await assetsLoaded();
        """)

    def test_b02_every_role_opens_home_with_no_error(self):
        for person in (self.ceo, self.accountant, self.finance, self.maker, self.approver, self.officer, self.clerk, self.dispatch,
                       self.invoicer, self.recon, self.auditor):
            with self.subTest(role=person.login):
                self.check(HOME, """
                    await waitFor('.ei-home-inner');
                    must(document.querySelectorAll('meta[name=theme-color]').length === 1, 'more than one theme colour');
                    fits();
                    await assetsLoaded();
                """, login=person.login)

    def test_b03_light_and_dark_themes_survive_navigation_and_refresh(self):
        self.check(HOME, """
            await waitFor('.ei-home-inner');
            const dark = () => getComputedStyle(document.documentElement).getPropertyValue('--ei-bg').trim();
            must(dark().toUpperCase() === '#0E1626', 'dark colours are not applied: ' + dark());
            must(%s === '#0E1626', 'the phone bar is not dark');
            await odoo.__WOWL_DEBUG__.root.env.services.action.doAction('ei_contract_da.ei_contract_action');
            await waitFor('.o_kanban_view, .o_list_view');
            must(dark().toUpperCase() === '#0E1626', 'dark was lost when moving to another screen');
            const page = async () => (await (await fetch('/odoo')).text());
            must(/assets_web_dark/.test(await page()), 'a refresh would lose the dark theme');
            document.cookie = 'color_scheme=light; path=/';
            must(!/assets_web_dark/.test(await page()), 'choosing light does not reach the next page');
        """ % APP_COLOUR, login=self.maker.login, cookies={'color_scheme': 'dark'})
        self.check(HOME, """
            await waitFor('.ei-home-inner');
            const bg = getComputedStyle(document.documentElement).getPropertyValue('--ei-bg').trim();
            must(bg.toUpperCase() === '#F4F6FA', 'light colours are not applied: ' + bg);
            must(!document.cookie.includes('color_scheme=dark'), 'another browser picked up the first person\\'s choice');
        """, login=self.ceo.login, cookies={'color_scheme': 'light'})

    def test_b04_navigation_from_the_top_menu(self):
        self.check(HOME, """
            await waitFor('.ei-home-inner');
            const menus = await (await fetch('/web/webclient/load_menus')).json();
            must(Object.keys(menus).length > 3, 'the menu is empty');
            await odoo.__WOWL_DEBUG__.root.env.services.action.doAction('ei_bank_operations.ei_balance_check_action');
            await waitFor('.o_list_view');
            await odoo.__WOWL_DEBUG__.root.env.services.action.doAction('ei_close.ei_recon_centre_action');
            await waitFor('.ei-rx-card');
            fits();
        """, login=self.finance.login)

    def test_b05_a_reader_is_not_offered_new_and_a_maker_is(self):
        action = '/odoo/action-ei_contract_da.ei_contract_action'
        self.check(action, """
            await waitFor('.o_kanban_view, .o_list_view');
            must(!document.querySelector('.o-kanban-button-new, .o_list_button_add'), 'the auditor is offered New');
        """, login=self.auditor.login)
        self.check(action, """
            (await waitFor('.o-kanban-button-new, .o_list_button_add')).click();
            await waitFor('.o_form_view [name=contract_ref]');
        """, login=self.maker.login)

    def test_b06_contract_approval_shows_the_evidence_and_cancel_changes_nothing(self):
        url = '/odoo/action-ei_contract_da.ei_contract_action/%s'
        self.check(url % self.waiting.id, """
            await waitFor('.o_form_view');
            must(!document.querySelector('button[name=action_approve]'), 'the person who prepared it is offered Approve');
        """, login=self.maker.login)
        self.check(url % self.cancelled_look.id, """
            (await waitFor('button[name=action_approve]')).click();
            const dialog = await waitFor('.ei-ap');
            must(dialog.textContent.includes('BROWSER-KEEP'), 'the evidence does not name the contract');
            must(dialog.textContent.includes('b_maker'), 'the evidence does not say who prepared it');
            clickText('.ei-ap', 'Cancel');
            await new Promise((r) => setTimeout(r, 500));
            must(!document.querySelector('.ei-ap'), 'the dialog stayed open');
        """, login=self.approver.login)
        self.cancelled_look.invalidate_recordset()
        self.assertEqual(self.cancelled_look.state, 'reviewed')

    def test_b07_bank_matching_screen(self):
        self.check('/odoo/action-ei_matching.action_ei_matching', """
            await waitFor('.ei-mt-title');
            await waitFor('.ei-mt-head');
            for (let i = 0; i < 100 && !document.body.textContent.includes('BROWSER PAYER'); i++) { await new Promise((r) => setTimeout(r, 100)); }
            must(document.body.textContent.includes('BROWSER PAYER'), 'the imported bank line is not listed');
            fits();
        """, login=self.officer.login)

    def test_b08_supplier_invoice_side_by_side(self):
        self.check('/odoo/action-ei_invoice_extensions.ei_intake_action/%s' % self.intake.id, """
            const field = await waitFor('.o_field_widget[name=comparison_html]');
            for (const words of ['Supplier says', 'Contract says', 'DA says', 'Actually lifted']) {
                must(field.textContent.includes(words), 'missing: ' + words);
            }
        """, login=self.invoicer.login)

    def test_b09_financial_reports_and_who_may_see_them(self):
        self.check('/odoo/action-ei_reports.action_report_workspace', """
            await waitFor('.ei-ws-kpis');
            must(/preview/i.test(document.querySelector('.ei-ws-preview').textContent), 'not labelled as a preview');
            fits();
        """, login=self.finance.login)
        self.check('/odoo/action-ei_close.ei_subledger_action', """
            await waitFor('.o_list_view, .o_view_nocontent');
        """, login=self.accountant.login)


@tagged('post_install', '-at_install', 'ei')
class TestBrowserPhone(EiBrowserCase):
    browser_size = '390x844'
    touch_enabled = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ceo = cls.person('p_ceo', 'ei_management_dashboard.group_ei_management')
        cls.officer = cls.person('p_bank', 'ei_bank_operations.group_ei_bank_officer')

    def test_p01_sign_in_page_fits_a_phone_and_keeps_pinch_zoom(self):
        self.check('/web/login', """
            await waitFor('input[name=login]');
            const viewport = document.querySelector('meta[name=viewport]').content;
            must(viewport.includes('viewport-fit=cover') && !viewport.includes('user-scalable=no'), 'viewport is ' + viewport);
            fits();
        """)

    def test_p02_the_app_shell_on_a_phone(self):
        for person in (self.ceo, self.officer):
            with self.subTest(role=person.login):
                self.check(HOME, """
                    await waitFor('.ei-home-inner');
                    await waitFor('.ei-bn');
                    must(document.querySelectorAll('.ei-bn-item').length >= 2, 'the bottom bar has no sections');
                    fits();
                """, login=person.login)

    def test_p03_screens_fit_a_phone(self):
        self.check('/odoo/action-ei_close.ei_recon_centre_action', """
            await waitFor('.ei-rx-card, .ei-rx-msg');
            fits();
        """, login=self.ceo.login)
