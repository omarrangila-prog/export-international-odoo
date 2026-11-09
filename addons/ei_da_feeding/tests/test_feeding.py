"""The six feeding methods against the client's handwritten examples (one sample DA, six ALTERNATIVE workings),
and the controls around a real entry. Customers, codes and parents here are synthetic."""
from decimal import Decimal

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ei_da_feeding.models import feeding_engine as fe

# fixture: (method, purchase/MTL, sale/MTL, spread/MTL, spread over 4.574 MTL) - from the handwritten sample DA
GOLDEN = [
    ('normal_sale', '268051.41', '270080.81', '2029.40', '9282.48'),
    ('high_profit_sale', '268051.41', '281080.81', '13029.40', '59596.48'),
    ('loss_sale', '268051.41', '261080.81', '-6970.60', '-31883.52'),
    ('sale_at_mill_rate', '268051.41', '271080.81', '3029.40', '13856.48'),
    ('purchase_with_cn', '267064.61', '271080.81', '4016.20', '18370.10'),
    ('direct_no_commission', '229500.00', '230500.00', '1000.00', '4574.00'),
]
PARAMS = {'sales_tax_pct': '18', 'additional_pct': '0.1', 'commission_pct': '1.32', 'cn_amount': '0', 'cn_commission_pct': '1.32'}


@tagged('post_install', '-at_install', 'ei')
class TestFeeding(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ei.approval.policy'].sudo().set_all(True)        # these tests check the second-person controls (policy on)
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'tz': 'Asia/Karachi', 'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.maker = mk('f_maker', 'ei_contract_da.group_ei_contract_staff')
        cls.checker = mk('f_chk', 'ei_contract_da.group_ei_contract_approver')
        cls.over = mk('f_over', 'ei_contract_da.group_ei_da_override', 'ei_contract_da.group_ei_contract_approver')
        cls.acct = mk('f_acct', 'ei_contract_da.group_ei_formula_approver')
        cls.mapper = mk('f_map', 'ei_legacy_master.group_ei_mapping_approver')
        cls.parent = cls.env['res.partner'].create({'name': 'Synthetic Steel Mill'})
        cls.cust = cls.env['res.partner'].create({'name': 'Alpha Traders'})
        cls.other = cls.env['res.partner'].create({'name': 'Beta Metals'})
        cls.prod = cls.env['product.product'].create({'name': 'GI coil 0.5mm', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        cls.formula = cls.env.ref('ei_contract_da.formula_isl_asml_dealer_net')
        if cls.formula.state == 'draft':
            cls.formula.with_user(cls.acct).action_approve()
        batch = cls.env['ei.import.batch'].sudo().create({'name': 'synthetic'})
        code = lambda c, sheet, name, nick=False: cls.env['ei.legacy.code'].sudo().create({
            'legacy_code': c, 'source_sheet': sheet, 'source_sheet_key': sheet, 'source_row': 1, 'original_name': name,
            'nickname': nick, 'batch_id': batch.id})
        cls.code_alpha = code('9.01', 'CUSTOMER', 'ALPHA TRADERS', 'ALPHA')
        cls.code_gamma = code('9.02', 'CUSTOMER', 'GAMMA MARKET SHOP', 'GAMMA.M')     # verified for Beta Metals: a different name than the paper
        cls.code_new = code('9.03', 'CUSTOMER', 'UNVERIFIED PARTY')
        cls.code_trade = code('19.03', 'FOR PURCHASE', 'MILL ALPHA PUR & SLS', 'MILL ALPHA')
        cls.code_pl = code('17.05', 'PROFIT & LOSS', 'MILL ALPHA P&L')
        cls.code_420 = code('4.20', 'FOR PURCHASE', 'SECURITY DEPOSIT')
        for c, p in ((cls.code_alpha, cls.cust), (cls.code_gamma, cls.other)):
            c.with_context(ei_system_write=True).write({'verification_status': 'approved', 'approved_target_type': 'res_partner',
                                                        'linked_model': 'res.partner', 'linked_res_id': p.id})
        cls.desk = cls.env['ei.feeding.desk'].with_user(cls.maker)

    def contract(self, currency=None):
        c = self.env['ei.contract'].with_user(self.maker).create({
            'parent_partner_id': self.parent.id, 'contract_ref': 'SYN-1', 'currency_id': (currency or self.env.company.currency_id).id,
            'contract_type': 'commission',
            'line_ids': [Command.create({'product_id': self.prod.id, 'ordered_mtl': 100, 'basic_rate': 229500, 'formula_id': self.formula.id,
                                         'purchase_rate': 268051.41, 'sale_rate': 271080.81,
                                         'param_ids': [Command.create({'key': k, 'value': v}) for k, v in PARAMS.items()]})]})
        self.env['ir.attachment'].sudo().create({'name': 'c.pdf', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        c.with_user(self.maker).action_review()
        c.with_user(self.checker).action_approve()
        c.with_user(self.maker).action_activate()
        return c

    def new_da(self, c, printed='M/S ALPHA TRADERS'):
        da_id = self.desk.da_create({'contract_id': c.id, 'name': 'SYN-DA-1', 'date': '2026-11-06', 'order_datetime': '2026-11-06 16:03',
                                     'ship_date': '2026-11-06', 'printed_customer': printed})
        self.env['ir.attachment'].sudo().create({'name': 'd.pdf', 'res_model': 'ei.da', 'res_id': da_id, 'raw': b'x'})
        return self.env['ei.da'].browse(da_id)

    def coil(self, d, method, coil='COIL-A', **kw):
        vals = {'contract_line_id': d.contract_id.line_ids.id, 'coil_no': coil, 'grade': 'P', 'weight_kg': '4574.00', 'method': method,
                'basic_rate': '229500', 'sale_offset': {'normal_sale': '-1000', 'high_profit_sale': '10000', 'loss_sale': '-10000'}.get(method, '0'),
                'customer_id': self.cust.id, 'customer_code_id': self.code_alpha.id, 'trade_code_id': self.code_trade.id, 'pl_code_id': self.code_pl.id}
        if method == 'purchase_with_cn':
            vals.update(cn_amount='1000', cn_text='CN 1000 on this coil')
        if method == 'direct_no_commission':
            vals.update(purchase_rate='229500', sale_rate='230500')
        if method == 'loss_sale':
            vals.update(loss_reason='Clearing old stock (synthetic)')
        vals.update(kw)
        return self.env['ei.da.line'].browse(self.desk.save_line(d.id, False, vals)['line_id'])

    # ------------------------------------------------------------------ U01, U02, U16: the six examples, to the cent
    def test_01_practice_matches_the_six_handwritten_examples(self):
        lab = self.desk.lab()
        self.assertEqual(lab['quantity'], '4.574')                                       # 4,574.00 kg = 4.574 MTL exactly
        cards = {c['key']: c for c in lab['cards']}
        for method, purchase, sale, spread, total in GOLDEN:
            c = cards[method]
            self.assertTrue(c['ok'], (method, c.get('error')))
            self.assertEqual((c['purchase_rate'], c['sale_rate'], c['spread_per_mtl'], c['total_spread']), (purchase, sale, spread, total), method)
        steps = {r['key']: r['value'] for r in cards['purchase_with_cn']['rows']}
        self.assertEqual([steps[k] for k in ('sales_tax_18', 'after_sales_tax', 'additional_0_1', 'mill_rate', 'dealer_commission',
                                             'dealer_net_purchase_rate', 'cn_commission', 'net_cn', 'final_net_purchase_rate')],
                         ['41310.00', '270810.00', '270.81', '271080.81', '3029.40', '268051.41', '13.20', '986.80', '267064.61'])
        self.assertNotIn('net_cn', {r['key'] for r in cards['normal_sale']['rows']})    # a CN never appears on a method without one
        self.assertEqual({r['key'] for r in cards['direct_no_commission']['rows']}, {'purchase', 'sale'})   # no commission steps at all
        self.assertEqual(cards['loss_sale']['result'], 'loss')

    def test_02_row_4_is_sale_at_mill_rate_and_purchase_without_commission_is_not_invented(self):
        m = {x['key']: x for x in self.desk.methods()}
        self.assertEqual(m['sale_at_mill_rate']['label'], 'Sale at mill rate')
        self.assertFalse(m['purchase_without_commission']['ready'])
        card = next(c for c in self.desk.lab()['cards'] if c['key'] == 'purchase_without_commission')
        self.assertFalse(card['ok'])
        self.assertNotIn('purchase_rate', card)                                          # no numbers are shown for it
        self.assertEqual(len(m), 7)                                                     # six from the client + the pending one; no 'VA', no seventh rule
        self.assertFalse({'va', 'seventh'} & {k.lower() for k in m})
        d = self.new_da(self.contract())
        with self.assertRaises(UserError):
            self.coil(d, 'purchase_without_commission')

    def test_03_practice_writes_nothing(self):
        models_ = ('account.move', 'account.move.line', 'ei.da', 'ei.da.line', 'ei.contract', 'ir.attachment', 'mail.message')
        before = {m: self.env[m].sudo().search_count([]) for m in models_}
        for _i in range(3):
            self.desk.lab({'basic_rate': '244450', 'weight_kg': '1000'})
        self.assertEqual(before, {m: self.env[m].sudo().search_count([]) for m in models_})

    def test_04_rounding_and_quantity_edges(self):
        self.assertEqual(fe.tons_from_kg('4574'), Decimal('4.574'))
        self.assertEqual(fe.tons_from_kg('1'), Decimal('0.001'))
        with self.assertRaises(fe.FeedingError):
            fe.feed('direct_no_commission', 0, purchase_rate=1, sale_rate=2)
        with self.assertRaises(fe.FeedingError):                                      # a sale offset that wipes out the price
            fe.feed('loss_sale', Decimal('4.574'), steps=self.formula._steps(), basic_rate='229500', params={k: Decimal(str(v)) for k, v in PARAMS.items() if k != 'cn_amount'}, sale_offset='-999999')
        r = fe.feed('direct_no_commission', Decimal('4.574'), purchase_rate='229500', sale_rate='229500')
        self.assertEqual((r['spread_per_mtl'], r['result']), (Decimal('0.00'), 'even'))

    # ------------------------------------------------------------------ real entry
    def test_05_real_coils_use_the_contract_formula_and_keep_their_own_cn(self):
        d = self.new_da(self.contract())
        a = self.coil(d, 'purchase_with_cn', 'COIL-A')
        b = self.coil(d, 'sale_at_mill_rate', 'COIL-B')
        self.assertEqual((a.purchase_rate, a.sale_rate, a.cn_amount), (267064.61, 271080.81, 1000.0))
        self.assertEqual((b.purchase_rate, b.sale_rate, b.cn_amount, b.cn_text), (268051.41, 271080.81, 0.0, False))   # U15
        self.assertEqual((a.mtl, a.spread_per_mtl, a.gross_spread), (4.574, 4016.2, 18370.1))
        self.assertEqual(a.feeding_calc['formula']['code'], 'ISL_ASML_DEALER_NET')
        with self.assertRaises(UserError):
            self.coil(d, 'sale_at_mill_rate', 'COIL-A')                                  # same coil twice on one DA
        d.with_user(self.maker).action_review()
        d.with_user(self.checker).action_approve()
        self.assertEqual(d.state, 'approved')

    def test_06_dates_stay_apart(self):
        d = self.new_da(self.contract())
        self.assertEqual(str(d.date), '2026-11-06')
        self.assertEqual(fields.Datetime.to_string(d.order_datetime), '2026-11-06 11:03:00')   # 16:03 in Karachi, stored in UTC
        self.assertEqual(self.desk.da_load(d.id)['order_datetime'], '2026-11-06 16:03')
        self.assertEqual(str(d.ship_date), '2026-11-06')
        d.write({'date': '2026-11-07'})                                                     # the DA date can be set apart from the printed order time
        self.assertEqual(fields.Datetime.to_string(d.order_datetime), '2026-11-06 11:03:00')

    def test_07_a_printed_customer_that_does_not_match_the_code_blocks_approval(self):
        d = self.new_da(self.contract(), printed='M/S ALPHA TRADERS')
        line = self.coil(d, 'normal_sale', customer_code_id=self.code_gamma.id, customer_id=self.other.id)
        self.assertIn("prints 'M/S ALPHA TRADERS'", line.code_issue)
        d.with_user(self.maker).action_review()
        with self.assertRaises(UserError) as e:
            d.with_user(self.checker).action_approve()
        self.assertIn('9.02', str(e.exception))
        with self.assertRaises(AccessError):
            line.with_user(self.maker).action_authorise_code('looks fine')
        line.with_user(self.over).action_authorise_code('Gamma is the trading name on this account (synthetic)')
        self.assertFalse(line.code_issue)
        d.with_user(self.checker).action_approve()
        self.assertEqual(d.state, 'approved')

    def test_08_an_unverified_or_foreign_code_can_never_be_waved_through(self):
        d = self.new_da(self.contract())
        line = self.coil(d, 'normal_sale', customer_code_id=self.code_new.id)
        self.assertIn('not yet verified', line.code_issue)
        with self.assertRaises(UserError):
            line.with_user(self.over).action_authorise_code('trust me')
        line2 = self.coil(d, 'normal_sale', 'COIL-B', customer_id=self.other.id)
        self.assertIn('belongs to Alpha Traders', line2.code_issue)
        with self.assertRaises(UserError):
            self.coil(d, 'normal_sale', 'COIL-C', customer_code_id=self.code_trade.id)       # a purchase code is not a customer code
        d.with_user(self.maker).action_review()
        with self.assertRaises(UserError):
            d.with_user(self.checker).action_approve()

    def test_09_code_lookup_by_code_name_and_nickname_within_one_list(self):
        s = self.desk.code_search
        self.assertEqual([c['code'] for c in s('trade', '19.03')], ['19.03'])
        self.assertEqual([c['code'] for c in s('customer', 'gamma.m')], ['9.02'])           # nickname
        self.assertEqual([c['code'] for c in s('pl', 'alpha')], ['17.05'])                  # name, P&L list only
        self.assertEqual([c['code'] for c in s('trade', '4.2')], ['4.20'])                  # stays the text 4.20
        self.assertEqual(self.code_420.legacy_code, '4.20')
        sug = s('trade', '', 'M/S MILL ALPHA')
        self.assertTrue(sug and all(c['suggested'] for c in sug))                           # offered, never chosen
        self.assertEqual(self.env['ei.legacy.code'].name_search('MILL ALPHA')[0][0], self.code_trade.id)

    def test_10_a_loss_needs_a_reason_and_another_person(self):
        d = self.new_da(self.contract())
        with self.assertRaises(UserError):
            self.coil(d, 'loss_sale', loss_reason='')
        self.coil(d, 'loss_sale')
        d.with_user(self.maker).action_review()
        with self.assertRaises(AccessError):
            d.with_user(self.maker).action_approve()                                       # U22: not your own
        d.with_user(self.checker).action_approve()

    def test_11_rates_changed_by_hand_after_the_calculation_are_refused(self):
        d = self.new_da(self.contract())
        line = self.coil(d, 'normal_sale')
        line.with_user(self.maker).write({'sale_rate': 290000})
        d.with_user(self.maker).action_review()
        with self.assertRaises(UserError) as e:
            d.with_user(self.checker).action_approve()
        self.assertIn('changed by hand', str(e.exception))

    def test_12_a_foreign_currency_needs_a_rate_and_shows_the_base_amount(self):
        # the company currency of a fresh test database may be USD: then the "foreign" one is PKR (only PKR and USD are allowed)
        foreign = self.env.ref('base.USD') if self.env.company.currency_id != self.env.ref('base.USD') else self.env.ref('base.PKR')
        foreign.active = True
        self.env['res.currency.rate'].search([('currency_id', '=', foreign.id)]).unlink()
        d = self.new_da(self.contract(currency=foreign))
        line = self.coil(d, 'direct_no_commission', purchase_rate='800', sale_rate='812')
        self.assertIs(d._fx(), False)
        self.assertIn('No %s rate' % foreign.name, d.fx_text)
        self.assertTrue(self.desk.da_load(d.id)['fx_missing'])
        d.with_user(self.maker).action_review()
        with self.assertRaises(UserError) as e:
            d.with_user(self.checker).action_approve()
        self.assertIn('No %s rate' % foreign.name, str(e.exception))
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'name': '2026-11-01', 'rate': 1 / 280.0,
                                              'company_id': self.env.company.id})
        d.invalidate_recordset(['fx_text'])
        prev = self.desk.preview(d.id, {'contract_line_id': d.contract_id.line_ids.id, 'method': 'direct_no_commission',
                                        'purchase_rate': '800', 'sale_rate': '812', 'weight_kg': '4574'})
        # the coil's own amount (54.89) converted, as Odoo converts a document amount: 54.89 x 280 = 15,369.20
        self.assertEqual((prev['currency'], prev['base']['purchase_rate'], prev['total_spread'], prev['base']['total_spread']),
                         (foreign.name, '224000.00', '54.89', '15369.20'))
        d.with_user(self.checker).action_approve()
        self.assertEqual((line.purchase_rate, line.sale_rate), (800.0, 812.0))                # the DA keeps its own currency

    def test_13_real_entry_refuses_a_formula_the_accountant_has_not_approved(self):
        draft = self.formula.with_user(self.acct).action_new_version()
        f2 = self.env['ei.formula.definition'].browse(draft['res_id'])
        line = self.env['ei.da.line']
        cl = self.contract().line_ids
        cl.with_context(ei_system=True).formula_id = f2
        with self.assertRaises(fe.FeedingError):
            line._feed(cl, {'feeding_method': 'normal_sale', 'basic_rate': 229500, 'weight_kg': 4574})
        self.assertTrue(next(c for c in self.desk.lab()['cards'] if c['key'] == 'normal_sale')['ok'])   # practice still works, labelled

    def test_14_a_contract_cannot_type_a_purchase_rate_its_formula_disagrees_with(self):
        c = self.env['ei.contract'].with_user(self.maker).create({
            'parent_partner_id': self.parent.id, 'contract_ref': 'SYN-2', 'contract_type': 'commission',
            'line_ids': [Command.create({'product_id': self.prod.id, 'ordered_mtl': 10, 'basic_rate': 229500, 'formula_id': self.formula.id,
                                         'purchase_rate': 229500 * 0.9868, 'sale_rate': 271080.81,      # "basic less 1.32%": the old misreading
                                         'param_ids': [Command.create({'key': k, 'value': v}) for k, v in PARAMS.items()]})]})
        self.env['ir.attachment'].sudo().create({'name': 'c.pdf', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        with self.assertRaises(UserError) as e:
            c.with_user(self.maker).action_review()
        self.assertIn('268051.41', str(e.exception))

    def test_15_feeding_history_and_credit_note_register_show_what_was_saved(self):
        d = self.new_da(self.contract())
        a = self.coil(d, 'purchase_with_cn', 'COIL-A', weight_kg='5120')
        self.coil(d, 'normal_sale', 'COIL-B')
        self.coil(d, 'loss_sale', 'COIL-C')
        self.assertEqual((a.cn_commission, a.net_cn, a.cn_total, a.formula_text), (13.2, 986.8, 5052.42, 'ISL_ASML_DEALER_NET v1'))
        hist = self.env.ref('ei_da_feeding.ei_feeding_history_action')
        rows = self.env['ei.da.line'].with_user(self.maker).search(eval(hist.domain) + [('da_id', '=', d.id)])
        self.assertEqual(len(rows), 3)
        by = {m: (s, r) for m, s, r in self.env['ei.da.line'].with_user(self.maker)._read_group(
            eval(hist.domain) + [('da_id', '=', d.id)], ['feeding_method'], ['gross_spread:sum', '__count'])}
        self.assertEqual(by['normal_sale'][0], 9282.48)
        self.assertEqual(by['loss_sale'][0], -31883.52)
        self.assertEqual(self.env['ei.da.line'].search_count([('da_id', '=', d.id), ('result', '=', 'loss')]), 1)
        reg = self.env.ref('ei_da_feeding.ei_cn_register_action')
        cn = self.env['ei.da.line'].with_user(self.maker).search(eval(reg.domain) + [('da_id', '=', d.id)])
        self.assertEqual(cn.mapped('coil_no'), ['COIL-A'])                 # only the coil with a CN
