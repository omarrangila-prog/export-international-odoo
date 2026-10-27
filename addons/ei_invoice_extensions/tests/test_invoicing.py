from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'ei')
class TestInvoicing(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        co = cls.company_data['company']
        cls.env = cls.env(user=1, context=dict(cls.env.context, allowed_company_ids=[co.id]))   # fixtures as superuser
        cls.env.user.company_ids |= co
        cls.env.user.company_id = co
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': co.id, 'company_ids': [Command.set([co.id])],
            'group_ids': [Command.set([cls.env.ref(g).id for g in gs])]})
        cls.clerk = mk('i_clerk', 'ei_invoice_extensions.group_ei_invoicing')
        cls.appr = mk('i_appr', 'ei_invoice_extensions.group_ei_invoice_approver')
        cls.rev = mk('i_rev', 'ei_material_lifting.group_ei_lifting_reviewer', 'ei_contract_da.group_ei_contract_approver',
                     'ei_daily_orders.group_ei_order_approver')
        cls.parent = cls.partner_a
        cls.cust1, cls.cust2 = cls.partner_b, cls.env['res.partner'].create({'name': 'Customer Two'})
        cls.prod = cls.env['product.product'].create({'name': 'HR Coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id,
                                                      'list_price': 1, 'taxes_id': [Command.set([])],
                                                      'property_account_income_id': cls.company_data['default_account_revenue'].id,
                                                      'property_account_expense_id': cls.company_data['default_account_expense'].id})
        c = cls.env['ei.contract'].create({'parent_partner_id': cls.parent.id, 'contract_ref': 'C-INV', 'line_ids': [Command.create({
            'product_id': cls.prod.id, 'ordered_mtl': 100, 'purchase_rate': 200000, 'sale_rate': 210000})]})
        cls.env['ir.attachment'].create({'name': 'c', 'res_model': 'ei.contract', 'res_id': c.id, 'raw': b'x'})
        c.action_review(); c.with_user(cls.rev).action_approve(); c.action_activate()
        c.line_ids.with_user(cls.rev).action_set_ownership('direct_dispatch', 'direct from mill')
        cls.contract = c
        cls.da = cls.mkda('DA-1', 10, cls.cust1)
        cls.order = cls.env['ei.daily.order'].generate_from_da(cls.da)
        cls.order.with_user(cls.rev).action_approve()
        cls.n = 0

    @classmethod
    def mkda(cls, name, mtl, cust):
        d = cls.env['ei.da'].create({'name': name, 'parent_partner_id': cls.parent.id, 'contract_id': cls.contract.id,
                                     'line_ids': [Command.create({'contract_line_id': cls.contract.line_ids.id, 'mtl': mtl,
                                                                  'customer_id': cust.id})]})
        cls.env['ir.attachment'].create({'name': 'd', 'res_model': 'ei.da', 'res_id': d.id, 'raw': b'x'})
        d.action_review(); d.with_user(cls.rev).action_approve()
        return d

    def lifting(self, da=None, mtl=4, verify=True):
        type(self).n += 1
        da = da or self.da
        l = self.env['ei.lifting'].create({'da_line_id': da.line_ids.id, 'vehicle_no': 'T%s' % self.n,
                                           'gate_pass_no': 'GP%s' % self.n, 'claimed_mtl': mtl})
        self.env['ir.attachment'].create({'name': 'g', 'res_model': 'ei.lifting', 'res_id': l.id, 'raw': b'x'})
        if verify:
            l.with_user(self.rev).action_verify()
        return l

    def intake(self, number='SUP-1', qty=10, rate=200000, total=None, tax=0, tax_ids=False, order=True, **kw):
        untaxed = qty * rate
        i = self.env['ei.supplier.intake'].with_user(self.clerk).create({
            'partner_id': self.parent.id, 'invoice_number': number, 'invoice_date': '2026-10-02',
            'stated_tax': tax, 'stated_total': total if total is not None else untaxed + tax,
            'tax_ids': [Command.set(tax_ids or [])],
            'line_ids': [Command.create({'da_line_id': self.da.line_ids.id, 'received_mtl': qty, 'unit_rate': rate,
                                         'order_line_id': self.order.line_ids.id if order else False})], **kw})
        self.env['ir.attachment'].create({'name': 'inv.pdf', 'res_model': 'ei.supplier.intake', 'res_id': i.id, 'raw': b'x'})
        return i

    # ---- T08
    def test_01_delayed_invoice_attaches_to_existing_order(self):
        counts = [self.env[m].search_count([]) for m in ('ei.contract', 'ei.da', 'ei.daily.order')]
        i = self.intake()
        i.action_check()
        self.assertEqual((i.state, i.issue_text), ('matched', False))
        i.with_user(self.clerk).action_create_bill()
        self.assertEqual(i.state, 'billed')
        self.assertEqual((i.bill_id.move_type, i.bill_id.state, i.bill_id.amount_total, i.bill_id.ref), ('in_invoice', 'draft', 2000000, 'SUP-1'))
        self.assertEqual(self.order.line_ids.invoice_ref, 'SUP-1')
        self.assertEqual([self.env[m].search_count([]) for m in ('ei.contract', 'ei.da', 'ei.daily.order')], counts)
        self.assertEqual((self.order.line_ids.lifted_mtl, self.da.lifted_mtl), (0, 0))   # invoice is not lifting
        self.assertFalse(self.env['stock.move'].search_count([('origin', 'ilike', 'SUP-1')]) if 'stock.move' in self.env else 0)

    def test_02_mismatches_are_blocked(self):
        for kw, text in (({'rate': 205000}, 'rate'), ({'qty': 11}, 'MTL expected'), ({'total': 123}, 'Stated total')):
            i = self.intake(number='M-%s' % text[:3], **kw)
            i.action_check()
            self.assertEqual(i.state, 'mismatch', kw)
            self.assertIn(text, i.issue_text)
            with self.assertRaises(UserError):
                i.action_create_bill()
        no_doc = self.intake(number='NODOC')
        self.env['ir.attachment'].search([('res_model', '=', 'ei.supplier.intake'), ('res_id', '=', no_doc.id)]).unlink()
        no_doc.action_check()
        self.assertEqual(no_doc.state, 'mismatch')

    def test_02b_side_by_side_shows_supplier_contract_da_and_lifting(self):
        i = self.intake(number='SBS-1', rate=205000)
        i.action_check()
        html = str(i.comparison_html)
        for words in ('Supplier says', 'Contract says', 'DA says', 'Actually lifted', 'Still to invoice', "needs an approver"):
            self.assertIn(words, html)
        self.assertIn('text-danger', html)                                 # the 5,000 rate difference is shown, in red

    def test_03_override_rules(self):
        i = self.intake(rate=205000)
        i.action_check()
        with self.assertRaises(AccessError):
            i.with_user(self.clerk).action_override()
        with self.assertRaises(UserError):
            i.with_user(self.appr).action_override()   # no note
        i.review_note = 'Parent confirmed new rate by letter'
        self.appr.group_ids = [Command.link(self.env.ref('ei_invoice_extensions.group_ei_invoicing').id)]
        j = self.env['ei.supplier.intake'].with_user(self.appr).create({
            'partner_id': self.parent.id, 'invoice_number': 'OWN', 'invoice_date': '2026-10-02', 'stated_total': 1,
            'review_note': 'x', 'line_ids': [Command.create({'da_line_id': self.da.line_ids.id, 'received_mtl': 1, 'unit_rate': 1})]})
        j.action_check()
        with self.assertRaises(AccessError):
            j.with_user(self.appr).action_override()   # maker-checker
        i.with_user(self.appr).action_override()
        self.assertEqual(i.state, 'reviewed')
        i.action_create_bill()
        self.assertEqual(i.bill_id.amount_total, 2050000)

    def test_04_editing_after_check_resets_state(self):
        i = self.intake()
        i.action_check()
        self.assertEqual(i.state, 'matched')
        i.line_ids.unit_rate = 1
        self.assertEqual(i.state, 'draft')
        i.line_ids.unit_rate = 200000
        i.action_check()
        i.with_user(self.clerk).action_create_bill()
        with self.assertRaises(UserError):
            i.line_ids.unit_rate = 5     # billed: locked

    def test_05_duplicate_invoice_number(self):
        self.intake(number='DUPE')
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.intake(number='DUPE')
        existing = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': self.parent.id, 'ref': 'IN-ACC',
                                                    'invoice_date': '2026-10-01', 'invoice_line_ids': [Command.create({'name': 'x', 'price_unit': 1})]})
        j = self.intake(number='IN-ACC')
        j.action_check()
        self.assertEqual(j.state, 'mismatch')
        self.assertIn('already exists in accounting', j.issue_text)

    def test_06_partial_bills_and_credit_note(self):
        first = self.intake(number='P1', qty=4)
        first.action_check(); first.action_create_bill()
        second = self.intake(number='P2', qty=7)
        second.action_check()
        self.assertEqual(second.state, 'mismatch')                 # only 6 MTL remain
        second.line_ids.received_mtl = 6
        second.stated_total = 6 * 200000
        second.action_check()
        self.assertEqual(second.state, 'matched')
        cn = self.env['ei.supplier.intake'].with_user(self.clerk).create({
            'kind': 'in_refund', 'partner_id': self.parent.id, 'invoice_number': 'CN1', 'invoice_date': '2026-10-05',
            'original_id': first.id, 'stated_total': 5 * 200000,
            'line_ids': [Command.create({'da_line_id': self.da.line_ids.id, 'received_mtl': 5, 'unit_rate': 200000})]})
        self.env['ir.attachment'].create({'name': 'cn', 'res_model': 'ei.supplier.intake', 'res_id': cn.id, 'raw': b'x'})
        cn.action_check()
        self.assertEqual(cn.state, 'mismatch')                     # 5 > 4 invoiced
        self.assertIn('exceeds the invoiced', cn.issue_text)
        cn.line_ids.received_mtl = 2
        cn.stated_total = 400000
        cn.action_check(); cn.action_create_bill()
        self.assertEqual(cn.bill_id.move_type, 'in_refund')

    def test_07_tax_computed_from_selected_tax(self):
        tax = self.company_data['default_tax_purchase']
        i = self.intake(number='TAX', qty=1, rate=200000, tax=tax.amount * 2000, total=200000 + tax.amount * 2000, tax_ids=tax.ids)
        i.action_check()
        self.assertEqual(i.state, 'matched', i.issue_text)
        j = self.intake(number='TAX2', qty=1, rate=200000, tax=1, total=200001, tax_ids=tax.ids)
        j.action_check()
        self.assertEqual(j.state, 'mismatch')
        self.assertIn('Stated tax', j.issue_text)

    def test_08_ocr_is_not_faked(self):
        with self.assertRaises(UserError):
            self.intake(number='OCR').action_ocr()

    # ---- customer invoicing
    def wizard(self, liftings, user=None, **line_kw):
        w = self.env['ei.invoice.wizard'].with_user(user or self.clerk).with_context(
            active_model='ei.lifting', active_ids=liftings.ids).create({})
        w.line_ids.write(line_kw) if line_kw else None
        return w

    def test_09_invoice_from_partial_lifting(self):
        l = self.lifting(mtl=4)
        self.assertEqual(l.invoice_status, 'to_invoice')
        inv = self.env['account.move'].browse(self.wizard(l).action_create()['domain'][0][2])
        self.assertEqual((len(inv), inv.move_type, inv.state, inv.partner_id), (1, 'out_invoice', 'draft', self.cust1))
        self.assertEqual((inv.invoice_line_ids.quantity, inv.invoice_line_ids.price_unit, inv.amount_total), (4, 210000, 840000))
        self.assertIn('gate pass', inv.invoice_line_ids.name)
        self.assertEqual((l.invoice_status, l.invoice_move_id), ('invoiced', inv))
        with self.assertRaises(UserError):
            self.wizard(l).action_create()                       # no double invoicing

    def test_10_unverified_not_billable_and_cancel_releases(self):
        d = self.lifting(mtl=1, verify=False)
        self.assertEqual(d.invoice_status, 'not_billable')
        with self.assertRaises(UserError):
            self.wizard(d).action_create()
        l = self.lifting(mtl=2)
        inv = self.env['account.move'].browse(self.wizard(l).action_create()['domain'][0][2])
        inv.button_cancel()
        l.invalidate_recordset()
        self.assertEqual(l.invoice_status, 'to_invoice')

    def test_11_one_invoice_per_customer(self):
        da2 = self.mkda('DA-2', 10, self.cust2)
        a, b = self.lifting(mtl=3), self.lifting(da=da2, mtl=5)
        c = self.lifting(mtl=1)
        moves = self.env['account.move'].browse(self.wizard(a + b + c).action_create()['domain'][0][2])
        self.assertEqual(len(moves), 2)
        self.assertEqual(sorted(moves.mapped('amount_total')), [840000, 1050000])

    def test_11b_customer_layout_and_output_log(self):
        self.cust1.write({'ei_invoice_grouping': 'per_da', 'ei_show_contract_ref': True, 'ei_invoice_note': 'Synthetic PO wording'})
        a, b = self.lifting(mtl=3), self.lifting(mtl=1)
        inv = self.env['account.move'].browse(self.wizard(a + b).action_create()['domain'][0][2])
        self.assertEqual(len(inv.invoice_line_ids), 1)                     # one line per DA and material, as this customer asked
        line = inv.invoice_line_ids
        self.assertEqual(line.quantity, 4)
        self.assertIn('2 loadings', line.name)
        self.assertIn('contract', line.name)
        self.assertIn('Synthetic PO wording', str(inv.narration))
        self.assertEqual(inv.ei_revision, 0)
        inv.with_user(self.clerk).action_ei_export_excel()
        inv.invalidate_recordset(['ei_output_ids', 'ei_revision'])
        self.assertEqual((inv.ei_revision, inv.ei_output_ids.kind, inv.ei_output_ids.move_state), (1, 'excel', inv.state))
        inv._ei_log_output('pdf')                                          # same lines: same revision
        inv.invalidate_recordset(['ei_output_ids', 'ei_revision'])
        self.assertEqual(inv.ei_revision, 1)
        if inv.state == 'draft':
            inv.invoice_line_ids.price_unit = 1
            inv._ei_log_output('pdf')
            inv.invalidate_recordset(['ei_output_ids', 'ei_revision'])
            self.assertEqual(inv.ei_revision, 2)                           # the customer got a changed invoice: a new revision
        with self.assertRaises(UserError):
            inv.ei_output_ids[:1].write({'revision': 9})

    def test_12_price_adjustment_controls(self):
        l = self.lifting(mtl=1)
        w = self.wizard(l)
        w.line_ids.unit_price = 200000
        with self.assertRaises(AccessError):
            w.action_create()
        w2 = self.wizard(l, user=self.appr)
        w2.line_ids.unit_price = 200000
        with self.assertRaises(UserError):
            w2.action_create()                                   # reason missing
        w2.line_ids.adjust_reason = 'agreed discount, email 3/10'
        inv = self.env['account.move'].browse(w2.action_create()['domain'][0][2])
        self.assertEqual(inv.amount_total, 200000)
        self.assertIn('adjusted', inv.message_ids[0].body)

    def test_13_reversal_after_invoicing_warns(self):
        l = self.lifting(mtl=1)
        self.wizard(l).action_create()
        l.with_user(self.rev).action_reverse('wrong truck')
        self.assertIn('credit note', l.billing_warning)

    # ---- T12 compliance
    def test_14_unconfigured_connector_is_never_success(self):
        inv = self.env['account.move'].create({'move_type': 'out_invoice', 'partner_id': self.cust1.id, 'invoice_date': '2026-10-01',
                                               'invoice_line_ids': [Command.create({'name': 'x', 'price_unit': 10})]})
        inv.action_post()
        inv.action_ei_submit_fbr()
        sub = inv.ei_submission_ids
        self.assertEqual((sub.state, sub.attempts), ('pending_configuration', 0))
        fbr = self.env.ref('ei_invoice_extensions.adapter_fbr')
        self.assertFalse(fbr.implemented)
        fbr.write({'state': 'sandbox'})
        sub.action_retry()
        self.assertEqual(sub.state, 'failed')                    # sandbox selected but no connector exists
        self.assertIn('No connector is implemented', sub.last_error)
        with self.assertRaises(UserError):
            self.env['ei.compliance.submission'].submit(self.env['account.move'], 'fbr')

    def test_15_failure_is_recoverable_and_idempotent(self):
        inv = self.env['account.move'].create({'move_type': 'out_invoice', 'partner_id': self.cust1.id, 'invoice_date': '2026-10-01',
                                               'invoice_line_ids': [Command.create({'name': 'x', 'price_unit': 10})]})
        inv.action_post()
        ad = self.env['ei.compliance.adapter'].create({'code': 'test_gw', 'name': 'Test gateway', 'kind': 'other', 'state': 'sandbox'})
        calls = []
        outcomes = iter([ConnectionError('timeout'), 'REF-1'])

        def fake(self_):
            calls.append(self_.idempotency_key)
            r = next(outcomes)
            if isinstance(r, Exception):
                raise r
            return r
        Sub = type(self.env['ei.compliance.submission'])
        with patch.object(Sub, '_send_test_gw', fake, create=True):
            sub = self.env['ei.compliance.submission'].submit(inv, 'test_gw')
            self.assertEqual((sub.state, sub.attempts, sub.last_error), ('failed', 1, 'timeout'))
            sub.action_retry()
            self.assertEqual((sub.state, sub.attempts, sub.external_ref), ('submitted', 2, 'REF-1'))
            again = self.env['ei.compliance.submission'].submit(inv, 'test_gw')   # repeat click
            sub.action_retry()
        self.assertEqual(again, sub)
        self.assertEqual(self.env['ei.compliance.submission'].search_count([('move_id', '=', inv.id)]), 1)
        self.assertEqual(len(calls), 2)                          # never sent again once submitted
        self.assertEqual(len(set(calls)), 1)                     # same idempotency key every time
        self.assertTrue(ad.last_success_at)

    def test_16_only_posted_invoices_submit(self):
        draft = self.env['account.move'].create({'move_type': 'out_invoice', 'partner_id': self.cust1.id,
                                                 'invoice_line_ids': [Command.create({'name': 'x', 'price_unit': 10})]})
        with self.assertRaises(UserError):
            draft.action_ei_submit_fbr()
