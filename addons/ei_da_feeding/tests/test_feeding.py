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
        pkr = cls.env.ref('base.PKR'); pkr.active = True
        if cls.env.company.currency_id != pkr:        # a bare test database keeps its books in USD; the client's company keeps them in PKR
            cls.env['res.currency.rate'].create({'currency_id': pkr.id, 'name': '2020-01-01', 'rate': 280.0, 'company_id': cls.env.company.id})

    def contract(self, currency=None):
        c = self.env['ei.contract'].with_user(self.maker).create({
            'parent_partner_id': self.parent.id, 'contract_ref': 'SYN-1', 'currency_id': (currency or self.env.ref('base.PKR')).id,
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

    def test_12_new_entries_are_in_pkr_only_and_an_older_foreign_da_still_shows_its_rate(self):
        """PKR only (client, 11 Nov 2026). A USD record that already exists is left as it is and still explains itself."""
        usd = self.env.ref('base.USD'); usd.active = True
        with self.assertRaises(UserError):
            self.contract(currency=usd)                                                   # no new entry in USD
        old = self.contract()
        self.env.cr.execute("UPDATE ei_contract SET currency_id = %s WHERE id = %s", (usd.id, old.id))      # an older USD contract
        old.invalidate_recordset()
        with self.assertRaises(UserError):
            self.desk.da_create({'contract_id': old.id, 'name': 'SYN-USD'})               # and no new DA against it
        self.assertNotIn(old.id, [c['id'] for c in self.desk.da_list()['contracts']])
        if self.env.company.currency_id != usd:                                           # its existing DAs keep showing the rate they need
            d = self.env['ei.da'].sudo().create({'name': 'SYN-OLD', 'parent_partner_id': self.parent.id, 'contract_id': old.id})
            self.env['res.currency.rate'].search([('currency_id', '=', usd.id)]).unlink()
            d.invalidate_recordset()
            self.assertIn('No USD rate', d.fx_text)

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

    # ------------------------------------------------------------------ one screen, three parties, no contract first (11 Nov 2026)
    def parties(self):
        self.parent.sudo().write({'ei_is_supplier_mill': True, 'ei_feeding_formula_id': self.formula.id})
        pin = self.env['res.partner'].search([('name', '=', 'Synthetic Buying Entity')], limit=1) \
            or self.env['res.partner'].create({'name': 'Synthetic Buying Entity', 'ei_is_purchase_in': True})
        return self.parent, pin

    def entry(self, name='SYN-FE-1', sold=True, printed=False):
        supplier, pin = self.parties()
        da_id = self.desk.da_create({'supplier_id': supplier.id, 'purchase_in_id': pin.id, 'sold_out_id': sold and self.cust.id or False,
                                     'name': name, 'date': '2026-11-11', 'printed_customer': printed})
        self.env['ir.attachment'].sudo().create({'name': 'd.pdf', 'res_model': 'ei.da', 'res_id': da_id, 'raw': b'x'})
        d = self.env['ei.da'].browse(da_id)
        return d, self.desk.ensure_line(da_id, self.prod.id)['contract_line_id']

    def test_20_one_entry_without_a_contract_keeps_the_three_parties(self):
        before = self.env['ei.contract'].sudo().search_count([])
        d, cl = self.entry()
        self.assertEqual((d.parent_partner_id, d.purchase_in_id.name, d.sold_out_id), (self.parent, 'Synthetic Buying Entity', self.cust))
        acc = d.contract_id
        self.assertEqual((acc.contract_type, acc.state, acc.currency_id.name, acc.purchase_in_id), ('feeding', 'active', 'PKR', d.purchase_in_id))
        self.assertIn('Not a signed contract', acc.notes)
        d2, cl2 = self.entry('SYN-FE-2')
        self.assertEqual((d2.contract_id, cl2), (acc, cl))                                # one running account and one line per material
        self.assertEqual(self.env['ei.contract'].sudo().search_count([]), before + 1)
        load = self.desk.da_load(d.id)
        self.assertEqual((load['supplier'], load['purchase_in'], load['sold_out']['name'], load['is_feeding'], load['currency']),
                         (self.parent.display_name, 'Synthetic Buying Entity', self.cust.display_name, True, 'PKR'))
        lst = self.desk.da_list()
        self.assertIn(self.parent.id, [p['id'] for p in lst['suppliers']])
        self.assertNotIn(acc.id, [c['id'] for c in lst['contracts']])                     # the account is never offered as a "contract"
        with self.assertRaises(UserError):
            self.desk.da_create({'supplier_id': self.cust.id, 'purchase_in_id': d.purchase_in_id.id, 'name': 'X'})     # not a mill

    def test_21_the_foxpro_direct_entry_gives_the_same_amounts(self):
        """Direct purchase and sale, as on the client's FoxPro screen: 4.574 MTL, sale 230,500, purchase 229,500 (synthetic codes)."""
        d, cl = self.entry()
        vals = {'contract_line_id': cl, 'coil_no': 'FX-1', 'weight_kg': '4574', 'method': 'direct_no_commission', 'purchase_rate': '229500',
                'sale_rate': '230500', 'customer_id': self.cust.id, 'customer_code_id': self.code_alpha.id, 'trade_code_id': self.code_trade.id,
                'pl_code_id': self.code_pl.id, 'thickness': '0.50', 'width': '1219'}
        p = self.desk.preview(d.id, vals)
        self.assertEqual((p['sale_total'], p['purchase_total'], p['total_spread'], p['spread_per_mtl'], p['currency']),
                         ('1054307.00', '1049733.00', '4574.00', '1000.00', 'PKR'))
        line = self.env['ei.da.line'].browse(self.desk.save_line(d.id, False, vals)['line_id'])
        self.assertEqual((line.sale_amount, line.purchase_amount, line.gross_spread, line.coil_thickness, line.coil_width),
                         (1054307.0, 1049733.0, 4574.0, '0.50', '1219'))
        self.assertEqual((line.customer_code_id, line.trade_code_id, line.pl_code_id), (self.code_alpha, self.code_trade, self.code_pl))
        self.assertEqual((line.da_parent_id, line.da_purchase_in_id, line.customer_id, line.sold_status), (self.parent, d.purchase_in_id, self.cust, 'sold'))

    def test_22_six_alternatives_and_several_coils_on_one_entry(self):
        d, cl = self.entry()
        base = {'contract_line_id': cl, 'weight_kg': '4574', 'basic_rate': '229500', 'customer_id': self.cust.id, 'customer_code_id': self.code_alpha.id}
        extra = {'normal_sale': {'sale_offset': '-1000'}, 'high_profit_sale': {'sale_offset': '10000'}, 'loss_sale': {'sale_offset': '-10000', 'loss_reason': 'x'},
                 'sale_at_mill_rate': {}, 'purchase_with_cn': {'cn_amount': '1000', 'cn_text': 'CN'}, 'direct_no_commission': {'purchase_rate': '229500', 'sale_rate': '230500'}}
        for i, (method, purchase, sale, spread, _total) in enumerate(GOLDEN):
            self.desk.save_line(d.id, False, dict(base, coil_no='C-%d' % i, method=method, **extra[method]))
        got = {l.feeding_method: (('%.2f' % l.purchase_rate), ('%.2f' % l.sale_rate), ('%.2f' % l.spread_per_mtl)) for l in d.line_ids}
        self.assertEqual(got, {m: (p, s, sp) for m, p, s, sp, _t in GOLDEN})
        self.assertEqual(len(d.line_ids), 6)
        with self.assertRaises(UserError):
            self.desk.save_line(d.id, False, dict(base, coil_no='C-X', method='purchase_without_commission'))    # still waiting for the client's rule
        d.with_user(self.maker).action_review()
        d.with_user(self.checker).action_approve()                                        # no agreed quantity to exceed, no rate note demanded
        self.assertEqual(d.state, 'approved')
        self.assertAlmostEqual(d.contract_id.line_ids.ordered_mtl, 27.444, places=3)      # the account shows what was fed
        self.assertEqual(self.env['account.move'].sudo().search_count([('ref', 'ilike', d.name)]), 0)     # feeding posts nothing to the books

    def test_23_printed_name_belongs_to_purchase_in_and_an_unsold_coil_waits(self):
        d, cl = self.entry('SYN-FE-3', sold=False, printed='M/S SOMEBODY ELSE')
        self.assertFalse(self.desk.da_load(d.id)['sold_out'])
        vals = {'contract_line_id': cl, 'coil_no': 'U-1', 'weight_kg': '1000', 'method': 'direct_no_commission', 'purchase_rate': '100', 'sale_rate': '110'}
        line = self.env['ei.da.line'].browse(self.desk.save_line(d.id, False, vals)['line_id'])
        self.assertEqual(line.sold_status, 'unsold')                                      # saved as a draft: not sold yet, nothing invented
        with self.assertRaises(UserError):
            self.desk.submit(d.id)                                                        # it cannot go on without Sold (OUT)
        self.desk.save_line(d.id, line.id, dict(vals, customer_id=self.cust.id, customer_code_id=self.code_alpha.id))
        self.assertFalse(line.code_issue)                                                 # the code is checked against Sold (OUT), not the printed name
        d.with_user(self.maker).action_review()
        with self.assertRaises(UserError) as e:
            d.with_user(self.checker).action_approve()
        self.assertIn('Purchase (IN)', str(e.exception))                                  # the printed name is compared with Purchase (IN)
        wrong = dict(vals, customer_id=self.cust.id, customer_code_id=self.code_gamma.id)
        self.assertIn('belongs to', self.desk.preview(d.id, wrong)['code_issue'] if d.state == 'draft' else self.env['ei.da.line']._code_problem_for(self.code_gamma, self.cust, False))

    def test_24_an_unsold_coil_and_a_line_without_target_carry_no_phantom_customer(self):
        """Found while filming (12 Nov 2026): an empty customer came to the screen as the text 'res.partner()', which the screen took
        for a chosen Sold (OUT) customer with no name."""
        d, cl = self.entry(sold=False)
        self.desk.save_line(d.id, False, {'contract_line_id': cl, 'coil_no': 'UNSOLD-1', 'weight_kg': '1000', 'method': 'direct_no_commission',
                                          'purchase_rate': '1000', 'sale_rate': '1001'})
        load = self.desk.da_load(d.id)
        self.assertIsNone(load['contract_lines'][0]['target_customer'])
        self.assertIsNone(load['lines'][0]['customer'])
        self.assertIsNone(load['sold_out'])

    def test_25_draft_delete_and_item_size(self):
        d, cl = self.entry('SYN-DEL-1')
        name = d.name
        self.desk.da_delete(d.id)
        self.assertFalse(self.env['ei.da'].search([('name', '=', name)]))
        d2, cl2 = self.entry('SYN-DEL-2')
        d2.with_context(ei_system=True).write({'state': 'under_review'})
        with self.assertRaises(UserError):
            self.desk.da_delete(d2.id)
        sized = self.env['product.product'].create({'name': 'SYN GI COIL 0.50X1219'})
        r = self.desk.ensure_line(d.id if d.exists() else self.entry('SYN-DEL-3')[0].id, sized.id)
        self.assertEqual(r['dims'], {'thickness': '0.50', 'width': '1219'})
        with self.assertRaisesRegex(UserError, 'width 1000'):
            self.desk.save_line(r['da']['id'], False, {'contract_line_id': r['contract_line_id'], 'coil_no': 'SZ-1', 'weight_kg': '1000',
                                                       'method': 'direct_no_commission', 'purchase_rate': '1000', 'sale_rate': '1001',
                                                       'thickness': '0.50', 'width': '1000'})
