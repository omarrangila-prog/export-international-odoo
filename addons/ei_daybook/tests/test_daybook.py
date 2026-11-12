"""Online feeding and the cash book, as shown in the client's old-system recording (12 Nov 2026), with SYNTHETIC codes and names:
the test codes T.xx stand in for the client's codes (the real ones stay out of this public repository). The amounts are the
recording's: two online receipts of 100,000 and 200,000; a balance brought forward of 14,603,760; a 10,000,000 cash entry whose
debit code is not in the code list."""
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ei_da_feeding.models.desk import dims_problem, item_dims


@tagged('post_install', '-at_install', 'ei')
class TestDaybook(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ei.approval.policy'].sudo().set_all(True)
        co = cls.env.company
        cls.env.ref('base.PKR').active = True
        g = lambda x: cls.env.ref(x).id
        mk = lambda login, *gs: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'TEST ' + login, 'login': 'tdb_' + login, 'company_id': co.id, 'company_ids': [Command.set([co.id])],
            'group_ids': [Command.set([g(x) for x in gs] + [g('ei_legacy_master.group_ei_user')])]})
        officer, bank_ap = 'ei_bank_operations.group_ei_bank_officer', 'ei_bank_operations.group_ei_bank_approver'
        clerk, cash_ap = 'ei_cashbook.group_ei_cash_clerk', 'ei_cashbook.group_ei_cash_approver'
        cls.maker = mk('maker', officer, clerk)
        cls.checker = mk('checker', officer, bank_ap, clerk, cash_ap)
        cls.senior = mk('senior', officer, bank_ap, clerk, cash_ap)          # enters AND checks (never their own)
        cls.clerk_only = mk('clerk', clerk)
        batch = cls.env['ei.import.batch'].create({'name': 'TEST codes'})
        code = lambda c, sheet, name: cls.env['ei.legacy.code'].create({
            'legacy_code': c, 'source_sheet': sheet, 'source_sheet_key': sheet, 'source_row': 0, 'original_name': name, 'batch_id': batch.id})
        cls.party_a = code('T.24', 'CUSTOMER', 'TEST PARTY A')
        cls.party_b = code('T.42', 'CUSTOMER', 'TEST PARTY B CASH 2')
        cls.bank_a = code('T.20', 'BANK', 'TEST BANK A')
        cls.bank_b = code('T.50', 'BANK', 'TEST BANK B')
        cls.safe = code('T.01', 'BANK', 'TEST SAFE')
        cls.bank_c = code('T.22', 'BANK', 'TEST BANK C')
        cls.E = cls.env['ei.daybook.entry']
        cls.R = cls.env['ei.approval.request']

    def entry(self, user=None, **kw):
        vals = dict(kind='online', date='2026-11-12', amount=100000, credit_code_id=self.party_a.id, debit_code_id=self.bank_a.id)
        vals.update(kw)
        return self.E.with_user(user or self.maker).create(vals)

    def approve(self, e, user=None):
        e.with_user(e.maker_id).action_submit()
        self.R._pending_for(e).with_user(user or self.checker).action_approve()
        return e

    # V4-035/036/037: the two online receipts give four lines, 300,000 Dr and 300,000 Cr, and the printed day book says the same
    def test_01_two_online_receipts_four_lines_equal_totals(self):
        a = self.approve(self.entry(credit_narration='RECEIVED', debit_narration='RECEIVED ONLINE'))
        b = self.approve(self.entry(amount=200000, credit_code_id=self.party_b.id, debit_code_id=self.bank_b.id))
        self.assertEqual((a.state, b.state), ('approved', 'approved'))
        legs = self.env['ei.daybook.leg'].search([('entry_id', 'in', (a | b).ids)])
        self.assertEqual(len(legs), 4)
        self.assertEqual((sum(legs.mapped('debit')), sum(legs.mapped('credit'))), (300000, 300000))
        self.assertEqual(legs.filtered(lambda l: l.code_id == self.bank_a).debit, 100000)
        self.assertEqual(legs.filtered(lambda l: l.code_id == self.party_b).credit, 200000)
        w = self.env['ei.daybook.print'].create({'date_from': '2026-11-12', 'date_to': '2026-11-12', 'kind': 'online'})
        d = w.report_data()
        self.assertEqual((d['debit_total'], d['credit_total'], len(d['moves'])), (300000, 300000, 2))
        pdf, _t = self.env['ir.actions.report']._render_qweb_html('ei_daybook.action_report_daybook', w.ids)
        self.assertIn(b'TEST PARTY B CASH 2', pdf)

    # V4-020 / V4-015: the debit side of an online entry is a BANK code; codes keep their text form
    def test_02_online_debit_must_be_a_bank_code(self):
        with self.assertRaisesRegex(UserError, 'not a BANK code'):
            self.entry(debit_code_id=self.party_b.id)
        e = self.entry()
        self.assertEqual(e.debit_code_id.legacy_code, 'T.20')
        self.assertEqual(e.debit_name, 'TEST BANK A')

    # V4-043/049: a balance brought forward is one code, printed apart, never a movement of the day, never two-sided
    def test_03_balance_brought_forward_stands_apart(self):
        with self.assertRaisesRegex(UserError, 'ONE code'):
            self.entry(user=self.maker, kind='opening', amount=14603760, credit_code_id=self.safe.id, debit_code_id=self.bank_c.id)
        with self.assertRaisesRegex(UserError, 'BANK code'):
            self.entry(kind='opening', amount=14603760, credit_code_id=self.party_a.id, debit_code_id=False)
        o = self.approve(self.entry(kind='opening', amount=14603760, credit_code_id=self.safe.id, debit_code_id=False,
                                    credit_narration='BALANCE BROUGHT FORWARD'), user=self.checker)
        c = self.approve(self.entry(kind='cash', amount=10000, credit_code_id=self.bank_c.id, debit_code_id=self.party_a.id, chq_no='TEST-1'))
        leg = self.env['ei.daybook.leg'].search([('entry_id', '=', o.id)])
        self.assertEqual((len(leg), leg.is_opening, leg.credit, leg.movement_credit), (1, True, 14603760, 0))
        d = self.env['ei.daybook.print'].create({'date_from': '2026-11-12', 'date_to': '2026-11-12', 'kind': 'cash'}).report_data()
        self.assertEqual(d['opening_total'], 14603760)
        self.assertEqual((d['debit_total'], d['credit_total']), (10000, 10000), 'the carried balance is not counted as the day')
        with self.assertRaisesRegex(UserError, 'already has a balance brought forward'):
            self.entry(kind='opening', amount=5, credit_code_id=self.safe.id, debit_code_id=False)
        self.assertEqual(c.chq_no, 'TEST-1')

    # V4-019/044: a code that is not in the code list (the recording shows one) is kept as a draft, never submitted or guessed
    def test_04_code_not_in_the_list_blocks_submission(self):
        e = self.entry(kind='cash', amount=10000000, credit_code_id=self.bank_c.id, debit_code_id=False, missing_code='99.99',
                       missing_side='debit', chq_no='CHQ-T', slip_no='SLIP-T', credit_narration='TEST', debit_narration='TEST')
        self.assertIn('99.99', e.code_warning)
        with self.assertRaisesRegex(UserError, '99.99 is not in the code list'):
            e.action_submit()
        self.assertEqual(e.state, 'draft')
        self.assertFalse(self.env['ei.daybook.leg'].search([('entry_id', '=', e.id), ('code_id', '=', False)]))

    # V4-040: the same payment cannot be fed twice
    def test_05_duplicates_are_refused(self):
        self.entry(proof_ref='SMS-T-1')
        with self.assertRaisesRegex(UserError, 'already on'):
            self.entry(amount=1, proof_ref='sms-t-1')
        with self.assertRaisesRegex(UserError, 'same date, amount and codes'):
            self.entry()
        self.entry(duplicate_ok_reason='TEST two real receipts of the same amount')

    # V4-053 / V4-052: nobody approves their own entry, whatever roles they hold; both seniors enter AND check each other's
    def test_06_maker_checker(self):
        e = self.entry(user=self.senior)
        e.with_user(self.senior).action_submit()
        req = self.R._pending_for(e)
        self.assertNotEqual(req.approver_id, self.senior)
        with self.assertRaises(AccessError):
            req.with_user(self.senior).action_approve()
        with self.assertRaises(AccessError):
            e.with_user(self.senior).action_approve()
        req.with_user(self.checker).action_approve()
        self.assertEqual((e.state, e.approved_by), ('approved', self.checker))
        f = self.entry(user=self.checker, amount=5)
        f.with_user(self.checker).action_submit()
        self.R._pending_for(f).with_user(self.senior).action_approve()
        self.assertEqual(f.approved_by, self.senior)

    # V4-011: PKR only
    def test_07_pkr_only(self):
        usd = self.env.ref('base.USD')
        with self.assertRaisesRegex(UserError, 'PKR only'):
            self.entry(currency_id=usd.id)
        e = self.entry()
        self.assertEqual(e.currency_id.name, 'PKR')
        with self.assertRaisesRegex(UserError, 'PKR only'):
            e.write({'currency_id': usd.id})

    # V4-058..061: draft edit and delete; an approved entry is neither edited nor deleted
    def test_08_edit_and_delete_draft(self):
        e = self.entry()
        e.write({'amount': 150000})
        self.assertEqual(e.amount, 150000)
        name = e.name
        e.unlink()
        self.assertTrue(self.env['ei.daybook.deleted'].search([('name', '=', name), ('deleted_by', '=', self.maker.id)]))
        a = self.approve(self.entry(amount=7))
        with self.assertRaisesRegex(UserError, 'Only a draft'):
            a.with_user(self.maker).write({'amount': 8})
        with self.assertRaisesRegex(UserError, 'corrected with Reverse'):
            a.with_user(self.maker).unlink()

    # V4-062: reversal - an equal entry with the sides swapped; both stay; the code ledgers net to zero
    def test_09_reverse(self):
        a = self.approve(self.entry())
        with self.assertRaises(AccessError):
            a.with_user(self.maker).action_reverse('TEST')
        a.with_user(self.checker).action_reverse('TEST wrong bank')
        self.assertEqual(a.state, 'reversed')
        rev = a.reversal_id
        self.assertEqual((rev.state, rev.credit_code_id, rev.debit_code_id, rev.amount), ('approved', self.bank_a, self.party_a, 100000))
        legs = self.env['ei.daybook.leg'].search([('entry_id', 'in', (a | rev).ids), ('code_id', '=', self.bank_a.id)])
        self.assertEqual(sum(legs.mapped('debit')) - sum(legs.mapped('credit')), 0)
        with self.assertRaisesRegex(UserError, 'Only an approved'):
            a.with_user(self.checker).action_reverse('again')

    # V4-055: returned with a note, corrected, submitted again; the history keeps both rounds
    def test_10_return_correct_resubmit(self):
        e = self.entry()
        e.action_submit()
        self.R._pending_for(e).with_user(self.checker).action_return('TEST wrong amount')
        self.assertEqual((e.state, e.approval_state), ('draft', 'returned'))
        e.write({'amount': 100001})
        e.action_submit()
        req = self.R._pending_for(e)
        self.assertEqual(req.round, 2)
        with self.assertRaisesRegex(UserError, 'Only a draft'):
            e.write({'amount': 1})           # nothing changes while a checker looks at it
        req.with_user(self.checker).action_approve()
        self.assertEqual(e.state, 'approved')

    # V4-041/042: proof is not bank confirmation; a pending entry is in no approved ledger
    def test_11_proof_is_not_bank_confirmation(self):
        e = self.entry(proof_ref='SMS-T-9')
        self.assertEqual(e.bank_status, 'proof')
        e.action_submit()
        approved = self.env['ei.daybook.leg'].search([('entry_id', '=', e.id), ('state', 'in', ('approved', 'reversed'))])
        self.assertFalse(approved)
        self.assertEqual(self.entry(amount=3).bank_status, 'entered')

    # roles: the cash desk cannot enter online receipts; nobody without the role links a bank statement line
    def test_12_roles(self):
        with self.assertRaises(AccessError):
            self.entry(user=self.clerk_only)
        e = self.entry(user=self.clerk_only, kind='cash', credit_code_id=self.party_a.id, debit_code_id=self.safe.id)
        self.assertEqual(e.kind, 'cash')

    # V4-023/024: an item's size decides thickness and width; a stale size is refused
    def test_13_item_size(self):
        self.assertEqual(item_dims('GI COIL 0.50X1219'), (__import__('decimal').Decimal('0.50'), __import__('decimal').Decimal('1219')))
        self.assertFalse(dims_problem('GI COIL 0.50X1219', '0.5', '1219'))
        self.assertIn('0.38', dims_problem('GI COIL 0.50X1219', '0.38', '1000'))
        self.assertFalse(dims_problem('HR coil 2mm', '0.38', '1000'), 'no size in the name: nothing to compare')

    def test_14_print_wizard_and_ledger_actions_open(self):
        self.approve(self.entry())
        w = self.env['ei.daybook.print'].with_user(self.maker).create({'date_from': '2026-11-12', 'date_to': '2026-11-12'})
        self.assertEqual(w.action_print()['type'], 'ir.actions.report')
        act = self.E.search([], limit=1).with_user(self.maker).action_open_ledger()
        self.assertEqual(act['res_model'], 'ei.daybook.leg')
