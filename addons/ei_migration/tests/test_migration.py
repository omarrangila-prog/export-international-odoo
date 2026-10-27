import json
import os
import tempfile

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.ei_migration.lib.dbf import Table
from odoo.addons.ei_migration.tests.dbf_fixture import write_table

import importlib.util
_spec = importlib.util.spec_from_file_location('foxpro_extract', os.path.join(os.path.dirname(__file__), '..', '..', '..', 'migration', 'foxpro_extract.py'))

FIELDS = [('CODE', 'C', 6, 0), ('NAME', 'C', 24, 0), ('AMOUNT', 'N', 12, 2), ('DATED', 'D', 8, 0), ('ACTIVE', 'L', 1, 0), ('NOTES', 'M', 10, 0)]
ROWS = [['4.20', 'Rehman Traders', '420000.00', '20261001', 'T', 0],
        ['16.10', 'Synthetic Mill', '-1500.50', '20261002', 'F', None],
        ['5.01', 'رحمان', '0.00', '20261003', 'T', 1]]


@tagged('post_install', '-at_install', 'ei')
class TestMigration(AccountTestInvoicingCommon):
    """Synthetic tables only: no client FoxPro data is in the repository."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        co = cls.company_data['company']
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': co.id, 'company_ids': [Command.set([co.id])],
            'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.acct = mk('m_acct', 'account.group_account_user')
        cls.mgr = mk('m_mgr', 'account.group_account_manager')

    def folder(self):
        d = tempfile.mkdtemp(prefix='ei_fox_')
        write_table(os.path.join(d, 'PARTY.DBF'), FIELDS, ROWS, memo_texts=['first note', 'نوٹ'], deleted={1})
        write_table(os.path.join(d, 'BANK.DBF'), [('ACNO', 'C', 4, 0), ('BAL', 'N', 14, 2)], [['B1', '580000.00'], ['B2', '12.30']], codepage=0x03)
        with open(os.path.join(d, 'MAIN.PRG'), 'w') as f:
            f.write('* synthetic program\n')
        return d

    def extract_module(self):
        mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(mod)
        return mod

    def test_01_reader_keeps_exact_text_deleted_records_memo_and_code_page(self):
        d = self.folder()
        t = Table(os.path.join(d, 'PARTY.DBF'))
        recs = list(t.records())
        self.assertEqual(len(recs), 3)
        self.assertEqual([r['CODE'] for r in recs], ['4.20', '16.10', '5.01'])          # codes stay text: 4.20 never becomes 4.2
        self.assertEqual(recs[0]['AMOUNT'], '420000.00')
        self.assertEqual(recs[1]['AMOUNT'], '-1500.50')
        self.assertEqual([r['_deleted'] for r in recs], [False, True, False])        # deleted, not dropped
        self.assertEqual((recs[0]['DATED'], recs[0]['ACTIVE'], recs[1]['ACTIVE']), ('2026-10-01', 'T', 'F'))
        self.assertEqual((recs[0]['NOTES'], recs[1]['NOTES'], recs[2]['NOTES']), ('first note', '', 'نوٹ'))
        self.assertEqual(recs[2]['NAME'], 'رحمان')                                    # Urdu read with the table's code page (cp1256)
        s = t.summary()
        self.assertEqual((s['codepage'], s['records_in_header'], s['records_found'], s['deleted']), ('cp1256', 3, 3, 1))

    def test_02_extract_is_read_only_complete_and_refuses_to_write_beside_the_source(self):
        mod, src = self.extract_module(), self.folder()
        before = {n: open(os.path.join(src, n), 'rb').read() for n in os.listdir(src)}
        with self.assertRaises(SystemExit):
            mod.extract(src, os.path.join(src, 'out'))
        out = tempfile.mkdtemp(prefix='ei_fox_out_')
        m = mod.extract(src, out)
        self.assertEqual({n: open(os.path.join(src, n), 'rb').read() for n in os.listdir(src)}, before)   # not one byte changed
        self.assertEqual(sorted(m['source_files']), ['BANK.DBF', 'MAIN.PRG', 'PARTY.DBF', 'PARTY.fpt'])
        party = next(t for t in m['tables'] if t['file'] == 'PARTY.DBF')
        self.assertEqual((party['records_found'], party['deleted']), (3, 1))
        with open(os.path.join(out, party['csv']), encoding='utf-8') as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0], '_recno,_deleted,CODE,NAME,AMOUNT,DATED,ACTIVE,NOTES')
        self.assertTrue(lines[1].startswith('1,,4.20,Rehman Traders,420000.00,2026-10-01,T,first note'))
        self.assertTrue(lines[2].startswith('2,Y,16.10'))
        return out

    def test_03_manifest_is_recorded_once_and_changes_are_shown(self):
        out = self.test_02_extract_is_read_only_complete_and_refuses_to_write_beside_the_source()
        data = open(os.path.join(out, 'manifest.json'), 'rb').read()
        E = self.env['ei.migration.extract'].with_user(self.acct)
        e1 = E.record_manifest(data)
        self.assertEqual((e1.n_tables, e1.n_records, e1.n_deleted, e1.source_files, e1.n_changed), (2, 5, 1, 4, 0))
        self.assertEqual(E.record_manifest(data), e1)                                 # the same extract twice is one extract
        m = json.loads(data)
        m['tables'][0]['sha256'] = 'changed'
        e2 = E.record_manifest(json.dumps(m).encode())
        self.assertEqual((e2.previous_id, e2.n_changed), (e1, 1))
        with self.assertRaises(UserError):
            E.record_manifest(b'{"format": "something else"}')
        with self.assertRaises(UserError):
            E.record_manifest(b'not json')
        return e1

    def test_04_control_totals_against_the_books_with_sign_off(self):
        ext = self.test_03_manifest_is_recorded_once_and_changes_are_shown()
        party = ext.table_ids.filtered(lambda t: t.file == 'PARTY.DBF')
        C = self.env['ei.migration.control'].with_user(self.acct)
        cnt = C.create({'cutoff': '2026-10-31', 'kind': 'table_count', 'label': 'Parties on old list', 'legacy_value': '2', 'table_id': party.id})
        self.assertEqual((cnt.odoo_value, cnt.status), (2, 'agrees'))                 # 3 records, 1 deleted
        cnt_all = C.create({'cutoff': '2026-10-31', 'kind': 'table_count', 'label': 'All rows', 'legacy_value': '3', 'table_id': party.id, 'deleted_rule': 'all'})
        self.assertEqual(cnt_all.status, 'agrees')
        inv = self.env['account.move'].create({'move_type': 'out_invoice', 'partner_id': self.partner_a.id, 'invoice_date': '2026-10-05',
                                               'invoice_line_ids': [Command.create({'name': 'coil', 'quantity': 1, 'price_unit': 1000, 'tax_ids': [Command.set([])]})]})
        inv.action_post()
        ar = C.create({'cutoff': '2026-10-31', 'kind': 'receivable', 'label': 'Debtors total', 'legacy_value': '1,250.00'})
        self.assertEqual((ar.odoo_value, ar.difference, ar.status), (1000, 250, 'differs'))
        bad = C.create({'cutoff': '2026-10-31', 'kind': 'receivable', 'label': 'Debtors', 'legacy_value': 'about a lakh'})
        self.assertEqual(bad.status, 'unreadable')
        neg = C.create({'cutoff': '2026-10-31', 'kind': 'receivable', 'label': 'x', 'legacy_value': '(1,000.00)'})
        self.assertEqual(neg.difference, -2000)
        with self.assertRaises(AccessError):
            ar.with_user(self.acct).action_sign()
        with self.assertRaises(UserError):
            ar.with_user(self.mgr).action_sign()                                       # a difference needs an explanation
        with self.assertRaises(UserError):
            bad.with_user(self.mgr).action_sign()
        ar.note = 'Synthetic: one old invoice of 250 not migrated yet.'
        ar.with_user(self.mgr).action_sign()
        cnt.with_user(self.mgr).action_sign()
        self.assertTrue(ar.signed_by and cnt.signed_by)
        with self.assertRaises(UserError):
            ar.write({'legacy_value': '1000'})
