from datetime import date
from decimal import Decimal

from odoo.tests import TransactionCase, tagged

from odoo.addons.ei_bank_operations.models import bank_parsing as bp


@tagged('post_install', '-at_install', 'ei')
class TestBankParsing(TransactionCase):

    def test_debit_credit_and_balance(self):
        r = bp.parse_statement_csv(b'Date,Description,Reference,Debit,Credit,Balance\n'
                                   b'01/10/2026,FROM ARIF,TX1,,"1,500,000.00","1,500,000.00"\n'
                                   b'02/10/2026,CHQ 55,,"(5,000)",,"1,495,000.00"\n')
        self.assertEqual(r.errors, [])
        self.assertEqual([l['amount'] for l in r.lines], [Decimal('1500000.00'), Decimal('-5000')])
        self.assertEqual(r.lines[0]['date'], date(2026, 10, 1))

    def test_bad_rows_reported(self):
        r = bp.parse_statement_csv(b'Date,Debit,Credit\n99/99/2026,1,\n01/10/2026,5,6\n01/10/2026,,\n')
        self.assertEqual(len(r.errors), 3)
        self.assertEqual(r.lines, [])

    def test_missing_columns(self):
        self.assertTrue(bp.parse_statement_csv(b'a,b\n1,2\n').errors)

    def test_fingerprint_ref_vs_occurrence(self):
        d = date(2026, 10, 1)
        self.assertEqual(bp.fingerprint(1, d, 5, 'tx 1', 'x', 1), bp.fingerprint(1, d, 5, 'TX 1', 'other', 2))
        self.assertNotEqual(bp.fingerprint(1, d, 5, '', 'x', 1), bp.fingerprint(1, d, 5, '', 'x', 2))
        self.assertNotEqual(bp.fingerprint(1, d, 5, '', 'x', 1), bp.fingerprint(2, d, 5, '', 'x', 1))
