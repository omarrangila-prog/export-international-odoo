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

    # Golden examples of the 11-page Daily Working Tasks, pp.3-5 (ISL_ASML_DEALER_NET), in both rounding modes
    DETAILED = [
        {'key': 'sales_tax_18', 'kind': 'tax_amount', 'base_ref': 'basic_rate', 'param': 'st'},
        {'key': 'after_sales_tax', 'kind': 'add_ref', 'base_ref': 'basic_rate', 'operand_ref': 'sales_tax_18'},
        {'key': 'additional_0_1', 'kind': 'tax_amount', 'base_ref': 'after_sales_tax', 'param': 'add'},
        {'key': 'mill_rate', 'kind': 'add_ref', 'base_ref': 'after_sales_tax', 'operand_ref': 'additional_0_1'},
        {'key': 'dealer_commission', 'kind': 'commission_amount', 'base_ref': 'basic_rate', 'param': 'cm'},
        {'key': 'dealer_net', 'kind': 'subtract_ref', 'base_ref': 'mill_rate', 'operand_ref': 'dealer_commission'},
        {'key': 'cn', 'kind': 'input_amount', 'base_ref': 'basic_rate', 'param': 'cn_amount'},
        {'key': 'cn_commission', 'kind': 'commission_amount', 'base_ref': 'cn', 'param': 'cm'},
        {'key': 'net_cn', 'kind': 'subtract_ref', 'base_ref': 'cn', 'operand_ref': 'cn_commission'},
        {'key': 'final', 'kind': 'subtract_ref', 'base_ref': 'dealer_net', 'operand_ref': 'net_cn'},
    ]

    def detailed(self, basic, cn=0, mode='final_only'):
        return fe.evaluate(self.DETAILED, basic, 1, {'st': '18', 'add': '0.1', 'cm': '1.32', 'cn_amount': str(cn)}, rounding_mode=mode)[1]

    def test_isl_and_asml_golden_examples(self):
        for mode in ('final_only', 'each_step'):
            isl = self.detailed(239950, mode=mode)
            self.assertEqual([isl[k] for k in ('sales_tax_18', 'after_sales_tax', 'additional_0_1', 'mill_rate', 'dealer_commission', 'dealer_net')],
                             [Decimal(x) for x in ('43191.00', '283141.00', '283.14', '283424.14', '3167.34', '280256.80')], mode)
            asml = self.detailed(244450, mode=mode)
            self.assertEqual([asml[k] for k in ('sales_tax_18', 'additional_0_1', 'mill_rate', 'dealer_commission', 'dealer_net')],
                             [Decimal(x) for x in ('44001.00', '288.45', '288739.45', '3226.74', '285512.71')], mode)

    def test_0_1_percent_is_on_the_18_percent_inclusive_rate_and_commission_on_the_basic_rate(self):
        v = self.detailed(239950)
        self.assertNotEqual(v['additional_0_1'], Decimal('239.95'))       # 0.1% of the basic rate would be the wrong reading
        self.assertNotEqual(v['dealer_commission'], Decimal('3741.20'))   # 1.32% of the mill rate would be the wrong reading
        self.assertNotEqual(v['mill_rate'], fe.evaluate(
            [{'key': 'm', 'kind': 'deduction_pct', 'base_ref': 'basic_rate', 'param': 'd'}], 239950, 1, {'d': '1.32'})[1]['m'])

    def test_cn_per_coil(self):
        for mode in ('final_only', 'each_step'):
            v = self.detailed(244450, cn=1000, mode=mode)
            self.assertEqual((v['cn_commission'], v['net_cn'], v['final']), (Decimal('13.20'), Decimal('986.80'), Decimal('284525.91')))
        self.assertEqual(self.detailed(244450)['final'], self.detailed(244450)['dealer_net'])   # no CN: final = dealer net
        # two coils of one invoice, each with its own CN: never one amount shared across them
        a, b = self.detailed(244450, cn=1000), self.detailed(244450, cn=250)
        self.assertEqual((a['final'], b['final']), (Decimal('284525.91'), Decimal('285266.01')))

    def test_reference_steps_refuse_unknown_results(self):
        with self.assertRaises(fe.FormulaError):
            fe.evaluate([{'key': 'x', 'kind': 'subtract_ref', 'base_ref': 'basic_rate', 'operand_ref': 'later'}], 1, 1, {})
