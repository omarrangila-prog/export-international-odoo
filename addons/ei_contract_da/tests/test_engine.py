from decimal import Decimal

from odoo.tests import TransactionCase, tagged

from odoo.addons.ei_contract_da.models import formula_engine as fe


@tagged('post_install', '-at_install', 'ei')
class TestEngine(TransactionCase):

    # T05
    def test_spread_example_from_pdf(self):
        self.assertEqual(fe.spread_per_unit(210000, 200000), 10000)
        self.assertEqual(fe.gross_spread(10, 210000, 200000), 100000)

    def test_spread_edge_cases(self):
        self.assertEqual(fe.gross_spread(0, 210000, 200000), 0)
        self.assertEqual(fe.gross_spread(10, 195000, 200000), -50000)       # negative spread is allowed
        self.assertEqual(fe.gross_spread(Decimal('2.5'), 210000, 200000), 25000)  # fractional MTL
        self.assertEqual(fe.gross_spread(10, 200000, 200000), 0)

    # T06
    def test_mill_rate_example(self):
        steps = [{'key': 'mill_rate', 'kind': 'deduction_pct', 'base_ref': 'basic_rate', 'param': 'ded'}]
        rows, vals = fe.evaluate(steps, 210000, 10, {'ded': '1.32'})
        self.assertEqual(vals['mill_rate'], Decimal('207228.00'))
        self.assertEqual(rows[0]['total'], Decimal('2072280.00'))

    def test_no_float_drift(self):
        steps = [{'key': 'r', 'kind': 'deduction_pct', 'base_ref': 'basic_rate', 'param': 'p'}]
        _r, v = fe.evaluate(steps, '199999.99', 1, {'p': '0.1'})
        self.assertEqual(v['r'], Decimal('199799.99'))

    def test_chain_and_variants(self):
        steps = [
            {'key': 'mill', 'kind': 'deduction_pct', 'base_ref': 'basic_rate', 'param': 'ded'},
            {'key': 'tax', 'kind': 'tax_amount', 'base_ref': 'mill', 'param': 'st'},
            {'key': 'addtax', 'kind': 'tax_amount', 'base_ref': 'mill', 'param': 'ast'},
            {'key': 'comm', 'kind': 'commission_amount', 'base_ref': 'basic_rate', 'param': 'cm'},
            {'key': 'ship', 'kind': 'fixed_add', 'base_ref': 'mill', 'param': 'sh'},
        ]
        _r, v = fe.evaluate(steps, 210000, 1, {'ded': 1.32, 'st': 18, 'ast': '0.1', 'cm': 0, 'sh': 500})
        self.assertEqual(v['tax'], Decimal('37301.04'))
        self.assertEqual(v['addtax'], Decimal('207.23'))
        self.assertEqual(v['comm'], Decimal('0.00'))
        self.assertEqual(v['ship'], Decimal('207728.00'))
        # tax contained in a tax-inclusive base is a DIFFERENT number from tax added on top
        inc = [{'key': 't', 'kind': 'tax_included_extract', 'base_ref': 'basic_rate', 'param': 'st'}]
        _r, w = fe.evaluate(inc, 118000, 1, {'st': 18})
        self.assertEqual(w['t'], Decimal('18000.00'))

    def test_rounding_modes_differ(self):
        steps = [{'key': 'a', 'kind': 'deduction_pct', 'base_ref': 'basic_rate', 'param': 'p'},
                 {'key': 'b', 'kind': 'tax_amount', 'base_ref': 'a', 'param': 't'}]
        prm = {'p': '0.45', 't': '13.5'}
        _r, final = fe.evaluate(steps, '12345.67', 1, prm, rounding_mode='final_only')
        _r, each = fe.evaluate(steps, '12345.67', 1, prm, rounding_mode='each_step')
        self.assertEqual((final['b'], each['b']), (Decimal('1659.17'), Decimal('1659.16')))

    def test_errors(self):
        with self.assertRaises(fe.FormulaError):
            fe.evaluate([{'key': 'x', 'kind': 'deduction_pct', 'base_ref': 'basic_rate', 'param': 'p'}], 1, 1, {})
        with self.assertRaises(fe.FormulaError):
            fe.evaluate([{'key': 'x', 'kind': 'deduction_pct', 'base_ref': 'later', 'param': 'p'}], 1, 1, {'p': 1})
        with self.assertRaises(fe.FormulaError):
            fe.evaluate([{'key': 'x', 'kind': 'python', 'base_ref': 'basic_rate', 'param': 'p'}], 1, 1, {'p': 1})
