import csv
import io

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from .test_parsing import source_bytes


@tagged('post_install', '-at_install', 'ei')
class TestLegacyMaster(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        g = lambda x: cls.env.ref('ei_legacy_master.' + x)
        cls.importer = Users.create({'name': 'Importer', 'login': 'ei_imp', 'group_ids': [(6, 0, [g('group_ei_importer').id])]})
        cls.approver = Users.create({'name': 'Approver', 'login': 'ei_app', 'group_ids': [(6, 0, [g('group_ei_mapping_approver').id])]})
        cls.auditor = Users.create({'name': 'Auditor', 'login': 'ei_aud', 'group_ids': [(6, 0, [g('group_ei_auditor').id])]})
        cls.Code = cls.env['ei.legacy.code']
        cls.batch = cls.env['ei.import.batch'].with_user(cls.importer).import_file('EXI_legacy_codes.csv', source_bytes())

    def code(self, c):
        return self.Code.search([('legacy_code', '=', c)], limit=1)

    # T01
    def test_01_import_counts_and_rerun_idempotent(self):
        self.assertEqual(self.batch.state, 'imported', self.batch.error_log)
        self.assertEqual(self.Code.search_count([]), 639)
        counts = dict(self.env['ei.legacy.code']._read_group([], ['source_sheet_key'], ['__count']))
        self.assertEqual(counts, {'CUSTOMER': 452, 'BANK': 79, 'IMPORT PUR SALE': 58,
                                  'FOR PURCHASE': 24, 'PROFIT & LOSS': 18, 'EXPENSES': 8})
        again = self.env['ei.import.batch'].with_user(self.importer).import_file('EXI_legacy_codes.csv', source_bytes())
        self.assertEqual((again.total_created, again.total_unchanged, again.total_changed), (0, 639, 0))
        self.assertEqual(self.Code.search_count([]), 639)

    def test_01b_code_text_preserved(self):
        for c, name in (('4.20', 'ELLAHI SECURITY/DOWN PAYMENT'), ('5.10', 'AL.HABIB CLOTH/MEHMOOD'),
                        ('16.10', 'FARHAN PERVAIZ LC 8114')):
            self.assertEqual(self.code(c).original_name, name)
        self.assertFalse(self.Code.search([('legacy_code', 'in', ('4.2', '5.1', '16.1'))]))
        self.assertEqual(self.code('4.20').source_row, 4)
        self.assertEqual(self.env['ei.legacy.code'].search([('source_sheet_key', '=', 'PROFIT & LOSS')])[0].source_sheet,
                         'PROFIT & LOSS ')

    def test_01c_bad_file_imports_nothing(self):
        before = self.Code.search_count([])
        bad = self.env['ei.import.batch'].import_file('x.csv', source_bytes().replace(b',4.20,', b',4.2,'))
        self.assertEqual(bad.state, 'failed')
        self.assertEqual(self.Code.search_count([]), before)

    def test_01d_changed_source_logs_diff_not_overwrite(self):
        data = source_bytes().replace(b'SALES SUSPENSE A/C', b'SALES SUSPENSE ACCOUNT')
        b2 = self.env['ei.import.batch'].import_file('v2.csv', data)
        self.assertEqual(b2.total_changed, 1)
        self.assertEqual(b2.diff_ids.old_value, 'SALES SUSPENSE A/C')
        self.assertEqual(self.code('4.19').original_name, 'SALES SUSPENSE A/C')
        with self.assertRaises(UserError):
            b2.with_user(self.approver).action_sign()

    # T02
    def test_02_suspected_bank_not_a_bank(self):
        c = self.code('5.83')
        self.assertTrue(c.is_exception)
        self.assertNotEqual(c.proposed_target_type, 'bank_journal')
        self.assertEqual(c.verification_status, 'needs_review')
        journals_before = self.env['account.journal'].search_count([])
        with self.assertRaises(UserError):
            c.with_user(self.approver).action_approve('bank_journal', 'because')
        with self.assertRaises(UserError):  # exception without a note
            c.with_user(self.approver).action_approve('suspense_account')
        self.assertEqual(self.env['account.journal'].search_count([]), journals_before)
        self.assertEqual(self.code('5.01').proposed_target_type, 'cash_journal')
        self.assertEqual(self.code('4.19').proposed_target_type, 'suspense_account')

    # permissions / maker-checker
    def test_03_permissions(self):
        c = self.code('1.01')
        with self.assertRaises(AccessError):
            c.with_user(self.auditor).write({'notes': 'x'})
        with self.assertRaises(AccessError):
            c.with_user(self.importer).action_approve('res_partner')
        with self.assertRaises(AccessError):  # maker-checker: importer who also holds approver rights
            self.importer.group_ids = [(4, self.env.ref('ei_legacy_master.group_ei_mapping_approver').id)]
            c.with_user(self.importer).action_approve('res_partner')
        c.with_user(self.approver).action_approve('res_partner')
        self.assertEqual((c.verification_status, c.approved_target_type, c.verified_by), ('approved', 'res_partner', self.approver))

    def test_04_raw_fields_immutable(self):
        c = self.code('1.01')
        for f, v in (('legacy_code', '1.1'), ('original_name', 'X'), ('nickname', 'Y')):
            with self.assertRaises(UserError):
                c.with_user(self.approver).write({f: v})
        with self.assertRaises(UserError):
            c.with_user(self.approver).write({'verification_status': 'approved'})  # no bypass of the workflow
        with self.assertRaises(UserError):
            c.with_user(self.approver).unlink()

    def test_05_sign_batch(self):
        with self.assertRaises(AccessError):
            self.batch.with_user(self.importer).action_sign()
        self.batch.with_user(self.approver).action_sign()
        self.assertEqual(self.batch.state, 'signed')
        self.assertTrue(self.code('1.01').batch_signed)

    def test_06_reconciliation_report_has_all_rows(self):
        raw = self.batch._reconciliation_csv().decode('utf-8-sig')
        rows = list(csv.DictReader(io.StringIO(raw)))
        self.assertEqual(len(rows), 639)
        self.assertIn('4.20', {r['legacy_code'] for r in rows})

    def test_07_multicompany_isolation(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        b = self.env['ei.import.batch'].with_company(other).import_file('EXI_legacy_codes.csv', source_bytes())
        self.assertEqual(b.total_created, 639)  # same codes allowed per company, no cross-company clash
        self.assertEqual(self.Code.search_count([]), 1278)
        g = self.env.ref('ei_legacy_master.group_ei_auditor')
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other auditor', 'login': 'ei_aud2', 'group_ids': [(6, 0, [g.id])],
            'company_ids': [(6, 0, [other.id])], 'company_id': other.id})
        self.assertEqual(self.Code.with_user(user).search_count([]), 639)
        self.assertEqual(set(self.Code.with_user(user).search([]).mapped('company_id')), {other})
        self.assertEqual(set(self.Code.with_user(self.auditor).search([]).mapped('company_id')), {self.env.company})
