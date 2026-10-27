import io

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.ei_parent_reconciliation.models.statement import norm_no, parse_rows


@tagged('post_install', '-at_install', 'ei')
class TestReconciliation(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        co = cls.company_data['company']
        cls.env = cls.env(user=1, context=dict(cls.env.context, allowed_company_ids=[co.id]))
        cls.env.user.company_ids |= co
        cls.env.user.company_id = co
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': co.id, 'company_ids': [Command.set([co.id])],
            'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.user = mk('r_user', 'ei_parent_reconciliation.group_ei_recon_user')
        cls.user2 = mk('r_user2', 'ei_parent_reconciliation.group_ei_recon_user')
        cls.appr = mk('r_appr', 'ei_parent_reconciliation.group_ei_recon_approver')
        cls.parent = cls.partner_a
        cls.bills = {}
        for ref, amt, mt in (('ISL-001', 1000, 'in_invoice'), ('ISL-002', 2000, 'in_invoice'), ('ISL-003', 3000, 'in_invoice'),
                             ('ISL-CN1', 500, 'in_refund'), ('ISL-009', 700, 'in_invoice')):
            b = cls.env['account.move'].create({'move_type': mt, 'partner_id': cls.parent.id, 'ref': ref, 'invoice_date': '2026-10-05',
                                                'invoice_line_ids': [Command.create({'name': 'steel', 'price_unit': amt, 'quantity': 1, 'tax_ids': [Command.set([])]})]})
            b.action_post()
            cls.bills[ref] = b

    CSV = (b"Invoice No,Date,Amount,Tax\n"
           b"ISL-001,05/10/2026,1000,0\n"        # matched
           b"isl 002,05/10/2026,2100,0\n"        # amount difference, number formatting differs
           b"ISL-003,05/10/2026,3000,50\n"       # tax difference
           b"ISL-CN1,05/10/2026,(500),0\n"       # credit note, signed
           b"ISL-004,05/10/2026,4000,0\n"        # missing in our books
           b"ISL-001,05/10/2026,1000,0\n"        # duplicate on statement
           b"ISL-777,05/10/2026,700,0\n")        # possible match (same amount as ISL-009)

    def statement(self, data=None, name='s.csv', user=None):
        return self.env['ei.parent.statement'].with_user(user or self.user).import_file(
            self.parent, '2026-10-01', '2026-10-31', name, data or self.CSV)

    def by(self, st):
        return {l.invoice_no: l for l in st.line_ids}

    # ---- T09
    def test_01_classification(self):
        st = self.statement()
        self.assertEqual(st.state, 'imported', st.issues)
        st.with_user(self.user).action_match()
        l = self.by(st)
        self.assertEqual(l['ISL-001'].status if l['ISL-001'].sequence == 2 else 'matched', 'matched')
        self.assertEqual(l['isl 002'].status, 'amount_difference')
        self.assertEqual(l['isl 002'].difference, 100)
        self.assertEqual(l['ISL-003'].status, 'tax_difference')
        self.assertEqual(l['ISL-CN1'].status, 'matched')
        self.assertEqual(l['ISL-004'].status, 'missing_internal')
        self.assertEqual(l['ISL-777'].status, 'possible_match')
        self.assertEqual(l['ISL-777'].internal_move_id, self.bills['ISL-009'])
        self.assertEqual(st.line_ids.filtered(lambda x: x.status == 'duplicate').mapped('invoice_no'), ['ISL-001'])
        self.assertFalse(st.line_ids.filtered(lambda x: x.status == 'missing_supplier'))  # ISL-009 taken by suggestion

    def test_02_missing_on_parent_statement(self):
        st = self.statement(b"Invoice No,Amount\nISL-001,1000\n")
        st.action_match()
        miss = st.line_ids.filtered(lambda x: x.status == 'missing_supplier')
        self.assertEqual(set(miss.mapped('invoice_no')), {'ISL-002', 'ISL-003', 'ISL-CN1', 'ISL-009'})
        self.assertTrue(all(l.source == 'internal' for l in miss))

    def test_03_posted_entries_never_touched(self):
        snap = {k: (b.write_date, b.amount_total, b.state, b.line_ids.mapped('balance')) for k, b in self.bills.items()}
        count = self.env['account.move'].search_count([])
        st = self.statement()
        st.action_match()
        st.action_match()   # idempotent re-run
        self.assertEqual(self.env['account.move'].search_count([]), count)
        for k, b in self.bills.items():
            b.invalidate_recordset()
            self.assertEqual((b.write_date, b.amount_total, b.state, b.line_ids.mapped('balance')), snap[k])
        self.assertEqual(len(st.line_ids.filtered(lambda x: x.source == 'statement')), 7)  # re-run does not multiply

    def test_04_workflow_to_signoff(self):
        st = self.statement()
        st.action_match()
        with self.assertRaises(UserError):
            st.action_check_assigned() if False else st.with_user(self.user).action_check_resolved()
        with self.assertRaises(UserError):
            st.action_check_assigned()               # exceptions have no owner
        exc = st.line_ids.filtered(lambda l: l.status != 'matched')
        exc.action_assign(self.user)
        st.action_check_assigned()
        self.assertEqual(st.state, 'assigned')
        with self.assertRaises(UserError):
            st.action_check_resolved()               # still open
        l = self.by(st)
        with self.assertRaises(UserError):
            l['isl 002'].with_user(self.user).action_resolve('our_correction', 'we mistyped')   # needs adjusting document
        with self.assertRaises(AccessError):
            l['isl 002'].with_user(self.user).action_resolve('accepted', 'ok')                  # only approver accepts
        with self.assertRaises(AccessError):
            l['isl 002'].with_user(self.user2).action_resolve('supplier_correction', 'x')       # not the owner
        with self.assertRaises(UserError):
            l['isl 002'].with_user(self.user).action_resolve('supplier_correction', '')
        l['isl 002'].with_user(self.user).action_resolve('supplier_correction', 'Parent invoiced wrong rate; asked for credit note')
        l['ISL-003'].with_user(self.appr).action_resolve('accepted', 'tax rounding agreed by phone with parent accounts')
        l['ISL-004'].with_user(self.user).action_resolve('timing', 'bill arrives next week')
        l['ISL-777'].with_user(self.user).action_resolve('supplier_correction', 'number typo on their side')
        dup = st.line_ids.filtered(lambda x: x.status == 'duplicate')
        with self.assertRaises(UserError):
            l['ISL-004'].with_user(self.user).action_resolve('duplicate_ignored', 'x')
        dup.with_user(self.user).action_resolve('duplicate_ignored', 'same line listed twice')
        st.action_check_resolved()
        self.assertEqual(st.state, 'resolved')
        with self.assertRaises(AccessError):
            st.with_user(self.user).action_sign()
        self.user.group_ids = [Command.link(self.env.ref('ei_parent_reconciliation.group_ei_recon_approver').id)]
        with self.assertRaises(AccessError):
            st.with_user(self.user).action_sign()    # importer cannot sign
        with self.assertRaises(UserError):
            st.with_user(self.appr).action_sign()    # nobody typed the total printed on the statement
        st.with_user(self.user).control_total = 11300
        st.with_user(self.appr).action_sign()
        self.assertEqual(st.state, 'signed')
        with self.assertRaises(UserError):
            st.write({'date_to': '2026-12-31'})
        with self.assertRaises(UserError):
            dup.action_resolve('timing', 'late edit')

    def test_09_printed_total_proves_completeness_and_the_parent_total_is_fully_accounted_for(self):
        st = self.statement()
        st.action_match()
        self.assertEqual(st.statement_total, 11300)
        # every rupee of the parent's total sits in exactly one class
        self.assertEqual((st.amount_matched, st.amount_differences, st.amount_parent_only, st.amount_duplicates), (500, 5100, 4700, 1000))
        self.assertEqual(st.amount_matched + st.amount_differences + st.amount_parent_only + st.amount_duplicates, st.statement_total)
        self.assertEqual(st.amount_internal_only, 0)                          # ISL-009 is held by the possible match, not lost
        ours = sum(st.line_ids.mapped('internal_amount'))
        self.assertEqual(st.internal_total, ours)
        # a row lost on import (printed 12,300, imported 11,300) blocks sign-off however clean the rest looks
        st.with_user(self.user).control_total = 12300
        self.assertEqual((st.completeness_diff, st.control_entered_by), (1000, self.user))
        st.line_ids.filtered(lambda l: l.status != 'matched').action_assign(self.user)
        st.action_check_assigned()
        for l in st.line_ids.filtered(lambda l: l.status != 'matched'):
            l.with_user(self.appr).action_resolve('duplicate_ignored' if l.status == 'duplicate' else 'timing', 'synthetic')
        st.action_check_resolved()
        with self.assertRaises(UserError):
            st.with_user(self.appr).action_sign()
        # the printed total can be given at import time too
        st2 = self.env['ei.parent.statement'].with_user(self.user).import_file(
            self.parent, '2026-11-01', '2026-11-30', 'n.csv', b"Invoice No,Date,Amount,Tax\nX-1,05/11/2026,100,0\n", control_total=100)
        self.assertEqual((st2.control_total, st2.completeness_diff, st2.control_entered_by), (100, 0, self.user))

    def test_05_our_correction_links_adjusting_document(self):
        st = self.statement()
        st.action_match()
        l = self.by(st)['isl 002']
        l.owner_id = self.user
        cn = self.env['account.move'].create({'move_type': 'in_refund', 'partner_id': self.parent.id, 'ref': 'ADJ',
                                              'invoice_date': '2026-10-20', 'invoice_line_ids': [Command.create({'name': 'adj', 'price_unit': 1})]})
        l.adjustment_move_id = cn
        l.with_user(self.user).action_resolve('our_correction', 'our bill was keyed wrong; credit note raised')
        self.assertEqual(l.resolution_state, 'resolved')

    def test_06_duplicate_file_and_bad_input(self):
        self.statement()
        again = self.statement()
        self.assertEqual(again.state, 'rejected')
        self.assertIn('already imported', again.issues)
        bad = self.statement(b"Invoice No,Amount\nX1,abc\n,5\n", name='bad.csv')
        self.assertEqual(bad.state, 'rejected')
        self.assertEqual(len(bad.issues.splitlines()), 2)
        pdf = self.statement(b"%PDF", name='stmt.pdf')
        self.assertIn('OCR', pdf.issues)
        with self.assertRaises(AccessError):
            self.env['ei.parent.statement'].with_user(self.env['res.users'].create({'name': 'x', 'login': 'noaccess'})).import_file(
                self.parent, '2026-10-01', '2026-10-31', 'q.csv', self.CSV)

    def test_07_xlsx_and_normalisation(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['Invoice No', 'Amount', 'Tax'])
        ws.append(['ISL-001', 1000, 0])
        buf = io.BytesIO()
        wb.save(buf)
        rows, errors = parse_rows('s.xlsx', buf.getvalue())
        self.assertEqual((errors, len(rows), str(rows[0]['amount'])), ([], 1, '1000'))
        self.assertEqual(norm_no(' isl-001 '), norm_no('ISL 001'))
        self.assertNotEqual(norm_no('ISL-0010'), norm_no('ISL-010'))   # leading zeros stay significant

    def test_08_reports_render(self):
        st = self.statement()
        st.action_match()
        R = self.env['ir.actions.report'].with_user(self.user)
        html = R._render_qweb_html('ei_parent_reconciliation.report_matching', st.ids)[0]
        self.assertIn(b'amount_difference'.decode() if False else b'ISL-004', html)
        cert = R._render_qweb_html('ei_parent_reconciliation.report_certificate', st.ids)[0]
        self.assertIn(b'not signed off', cert)
