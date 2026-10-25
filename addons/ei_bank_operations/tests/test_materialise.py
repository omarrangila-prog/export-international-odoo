from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.ei_legacy_master.tests.test_parsing import source_bytes


@tagged('post_install', '-at_install', 'ei')
class TestMaterialise(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda login, g: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([cls.env.ref(g).id])]})
        cls.importer = mk('m_imp', 'ei_legacy_master.group_ei_importer')
        cls.mapper = mk('m_map', 'ei_legacy_master.group_ei_mapping_approver')
        cls.env['ei.import.batch'].with_user(cls.importer).import_file('EXI.csv', source_bytes())
        cls.Code = cls.env['ei.legacy.code'].sudo()

    def code(self, c):
        return self.Code.search([('legacy_code', '=', c), ('company_id', '=', self.env.company.id)])

    def test_01_unapproved_not_materialised(self):
        with self.assertRaises(UserError):
            self.code('5.93').with_user(self.mapper).action_materialise()
        with self.assertRaises(AccessError):
            self.code('5.93').with_user(self.importer).action_materialise()

    def test_02_bank_journal_from_approved_code(self):
        c = self.code('5.93')
        c.with_user(self.mapper).action_approve('bank_journal')
        before = self.env['account.journal'].search_count([])
        c.with_user(self.mapper).action_materialise()
        j = self.env['account.journal'].sudo().browse(c.linked_res_id)
        self.assertEqual((j.type, j.code, j.name), ('bank', 'B593', 'AL.HABIB/EXPORT INTERNATIONAL'))
        c.with_user(self.mapper).action_materialise()  # idempotent
        self.assertEqual(self.env['account.journal'].search_count([]), before + 1)

    def test_03_suspected_bank_never_becomes_journal(self):
        c = self.code('5.83')
        with self.assertRaises(UserError):
            c.with_user(self.mapper).action_approve('bank_journal', 'x')
        before = self.env['account.journal'].search_count([])
        c.with_user(self.mapper).action_approve('suspense_account', 'Exception queue, confirmed by accountant')
        with self.assertRaises(UserError):
            c.with_user(self.mapper).action_materialise()
        self.assertEqual(self.env['account.journal'].search_count([]), before)

    def test_04_safe_as_cash_journal(self):
        c = self.code('5.01')
        c.with_user(self.mapper).action_approve('cash_journal', 'Office safe is cash, not a bank')
        c.with_user(self.mapper).action_materialise()
        self.assertEqual(self.env['account.journal'].sudo().browse(c.linked_res_id).type, 'cash')

    def test_05_partner_and_alias_proposals(self):
        c = self.code('1.03')
        c.with_user(self.mapper).action_approve('res_partner')
        c.with_user(self.mapper).action_materialise()
        p = self.env['res.partner'].sudo().browse(c.linked_res_id)
        self.assertEqual((p.name, p.ref), ('ARIF PATANWALA', '1.03'))
        aliases = self.env['ei.partner.alias'].sudo().search([('partner_id', '=', p.id)])
        self.assertEqual(set(aliases.mapped('alias')), {'ARIF PATANWALA', 'ARIF.P'})
        self.assertEqual(set(aliases.mapped('state')), {'proposed'})  # never auto-approved

    def test_06_same_name_codes_are_not_merged(self):
        codes = self.Code.search([('original_name', '=like', 'NAJAM ELLAHI%'), ('source_sheet_key', '=', 'CUSTOMER')])
        self.assertGreaterEqual(len(codes), 3)
        codes.with_user(self.mapper).action_approve('res_partner')
        codes.with_user(self.mapper).action_materialise()
        self.assertEqual(len(set(codes.mapped('linked_res_id'))), len(codes))

    def test_07_link_existing_partner(self):
        c = self.code('1.04')
        c.with_user(self.mapper).action_approve('res_partner')
        w = self.env['ei.legacy.link.wizard'].with_user(self.mapper).create({'code_id': c.id, 'partner_id': self.partner_a.id})
        w.action_link()
        self.assertEqual((c.linked_model, c.linked_res_id), ('res.partner', self.partner_a.id))

    def test_08_gl_account_not_auto_created(self):
        c = self.code('8.01')
        c.with_user(self.mapper).action_approve('gl_account')
        with self.assertRaises(UserError):
            c.with_user(self.mapper).action_materialise()
