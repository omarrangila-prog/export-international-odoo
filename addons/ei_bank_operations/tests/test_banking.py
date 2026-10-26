from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo import Command

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

HDR = 'Date,Description,Reference,Debit,Credit,Balance\n'


def csv(*rows):
    return (HDR + '\n'.join(rows) + '\n').encode()


@tagged('post_install', '-at_install', 'ei')
class TestBanking(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        g = lambda x: cls.env.ref(x).id
        mk = lambda login, *groups: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([g(x) for x in groups])]})
        cls.officer = mk('b_off', 'ei_bank_operations.group_ei_bank_officer')
        cls.approver = mk('b_app', 'ei_bank_operations.group_ei_bank_approver')
        cls.poster = mk('b_post', 'ei_bank_operations.group_ei_bank_poster')
        cls.journal = cls.company_data['default_journal_bank']
        cls.Import = cls.env['ei.bank.import']
        cls.pa, cls.pb = cls.partner_a, cls.partner_b

    def invoice(self, partner, amount, move_type='out_invoice'):
        inv = self.env['account.move'].create({
            'move_type': move_type, 'partner_id': partner.id, 'invoice_date': '2026-10-01',
            'invoice_line_ids': [Command.create({'name': 'steel', 'quantity': 1, 'price_unit': amount,
                                                 'tax_ids': [Command.set([])]})]})
        inv.action_post()
        return inv

    def stage(self, rows, opening=0, closing=None, name='s.csv', user=None):
        data = csv(*rows)
        total = sum(float(r.split(',')[4] or 0) - float(r.split(',')[3] or 0) for r in rows)
        return self.Import.with_user(user or self.officer).import_file(
            self.journal, name, data, opening, opening + total if closing is None else closing)

    def full_flow(self, batch, verify=None):
        """verify: {line: (partner, note)}; others unidentified. then approve + post by separate users."""
        for line in batch.line_ids.filtered(lambda l: l.state in ('new', 'proposed')):
            partner, note = (verify or {}).get(line.sequence, (None, None))
            if partner:
                line.with_user(self.officer).action_verify_partner(partner, note or 'payment image checked')
            else:
                line.with_user(self.officer).action_mark_unidentified('no counterparty known')
        return batch

    def approve_post(self, batch):
        batch.with_user(self.approver).action_approve()
        batch.with_user(self.poster).action_post()

    # --- T03 duplicates
    def test_01_duplicate_file_and_overlap(self):
        b1 = self.stage(['01/10/2026,RAAST FROM ARIF,TX1,,1000,1000', '02/10/2026,CASH DEP,,,500,1500'])
        self.assertEqual(b1.state, 'validated', b1.issues)
        again = self.stage(['01/10/2026,RAAST FROM ARIF,TX1,,1000,1000', '02/10/2026,CASH DEP,,,500,1500'])
        self.assertEqual(again.state, 'rejected')
        self.assertIn('already imported', again.issues)
        overlap = self.stage(['02/10/2026,CASH DEP,,,500,500', '03/10/2026,NEW,,,100,600'], name='o.csv')
        states = overlap.line_ids.sorted('sequence').mapped('state')
        self.assertEqual(states, ['duplicate', 'new'])
        self.assertEqual(self.env['ei.bank.import.line'].sudo().search_count([('journal_id', '=', self.journal.id), ('state', '=', 'new')]), 3)

    def test_02_identical_lines_in_one_file_stay_distinct(self):
        b = self.stage(['01/10/2026,FEE,,10,,-10', '01/10/2026,FEE,,10,,-20'], opening=0)
        self.assertEqual(b.state, 'validated', b.issues)
        self.assertEqual(len(set(b.line_ids.mapped('fingerprint'))), 2)

    def test_03_duplicate_not_posted_twice(self):
        b1 = self.full_flow(self.stage(['01/10/2026,DEP A,T9,,700,700']))
        self.approve_post(b1)
        stmt_lines = self.env['account.bank.statement.line'].search_count([('journal_id', '=', self.journal.id)])
        b2 = self.stage(['01/10/2026,DEP A,T9,,700,700', '02/10/2026,DEP B,,,50,750'], opening=0, name='again.csv')
        dup = b2.line_ids.filtered(lambda l: l.state == 'duplicate')
        self.assertEqual(len(dup), 1)
        self.full_flow(b2)
        b2.with_user(self.approver).write({'variance_note': 'opening differs: overlap'})
        self.approve_post(b2)
        self.assertEqual(self.env['account.bank.statement.line'].search_count([('journal_id', '=', self.journal.id)]), stmt_lines + 1)
        with self.assertRaises(UserError):
            b2.with_user(self.poster).action_post()  # already posted

    # --- balances
    def test_04_balance_differences_need_explanation(self):
        b = self.stage(['01/10/2026,DEP,,,100,100'], opening=0, closing=999)
        self.assertEqual(b.state, 'received')
        self.assertIn('Closing balance', b.issues)
        self.full_flow(b)
        with self.assertRaises(UserError):
            b.with_user(self.approver).action_approve()
        b.with_user(self.approver).write({'variance_note': 'bank closing includes uncleared item'})
        b.with_user(self.approver).action_approve()
        self.assertEqual(b.state, 'approved')

    def test_05_opening_vs_ledger(self):
        b = self.stage(['01/10/2026,DEP,,,100,600'], opening=500)
        self.assertEqual(b.state, 'received')
        self.assertIn('Opening balance', b.issues)
        self.assertEqual(b.opening_diff, 500)

    def test_06_morning_balance_check(self):
        Chk = self.env['ei.bank.balance.check'].with_user(self.approver)
        c = Chk.create({'journal_id': self.journal.id, 'bank_balance': 0, 'date': '2026-10-01'})
        self.assertEqual(c.state, 'matched')
        c2 = Chk.create({'journal_id': self.journal.id, 'bank_balance': 250, 'date': '2026-10-01'})
        self.assertEqual((c2.state, c2.difference), ('difference', 250))
        with self.assertRaises(UserError):
            c2.action_explain()
        with self.assertRaises(UserError):
            c2.write({'bank_balance': 0})
        c2.note = 'cheque 123 not yet entered'
        c2.action_explain()
        self.assertEqual(c2.state, 'explained')
        self.assertTrue(self.journal.ei_last_balance_check_at)

    # --- unidentified + verified party
    def test_07_unknown_deposit_cannot_be_allocated(self):
        inv = self.invoice(self.pa, 1000)
        b = self.stage(['01/10/2026,UNKNOWN DEP,,,1000,1000'])
        line = b.line_ids
        with self.assertRaises(UserError):  # no verified counterparty
            self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': line.id, 'invoice_id': inv.id, 'amount': 1000})
        line.with_user(self.officer).action_mark_unidentified('no idea')
        with self.assertRaises(UserError):
            self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': line.id, 'invoice_id': inv.id, 'amount': 1000})
        self.approve_post(b)
        st = line.statement_line_id
        self.assertFalse(st.partner_id)
        self.assertEqual(inv.payment_state, 'not_paid')
        self.assertTrue(st.move_id.line_ids.filtered(lambda l: l.account_id == self.journal.suspense_account_id))

    def test_08_verify_needs_evidence_unless_alias(self):
        b = self.stage(['01/10/2026,SOMEONE,,,10,10'])
        with self.assertRaises(UserError):
            b.line_ids.with_user(self.officer).action_verify_partner(self.pa)
        b.line_ids.with_user(self.officer).action_verify_partner(self.pa, 'payment image in group checked')
        self.assertEqual(b.line_ids.state, 'verified')
        with self.assertRaises(AccessError):
            b.line_ids.with_user(self.poster).action_verify_partner(self.pa, 'x')

    # --- T04 reconciliation
    def test_09_one_receipt_many_invoices(self):
        i1, i2 = self.invoice(self.pa, 1000), self.invoice(self.pa, 500)
        b = self.stage(['01/10/2026,ARIF PAYMENT,TX55,,1500,1500'])
        line = b.line_ids
        line.with_user(self.officer).action_verify_partner(self.pa, 'confirmed by bank call')
        for inv, amt in ((i1, 1000), (i2, 500)):
            self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': line.id, 'invoice_id': inv.id, 'amount': amt})
        bank_before = self.journal._ei_ledger_balance('2026-12-31')
        self.approve_post(b)
        self.assertEqual((i1.payment_state, i2.payment_state), ('paid', 'paid'))
        self.assertEqual(self.journal._ei_ledger_balance('2026-12-31') - bank_before, 1500)
        st = line.statement_line_id
        self.assertTrue(st.is_reconciled)
        self.assertFalse(st.move_id.line_ids.filtered(lambda l: l.account_id == self.journal.suspense_account_id))
        recv = self.env['account.move.line'].search([('partner_id', '=', self.pa.id), ('account_type', '=', 'asset_receivable'), ('parent_state', '=', 'posted')])
        self.assertAlmostEqual(sum(recv.mapped('amount_residual')), 0)

    def test_10_many_receipts_one_invoice_and_partial_remainder(self):
        inv = self.invoice(self.pa, 1000)
        b = self.stage(['01/10/2026,ARIF 1,T1,,600,600', '02/10/2026,ARIF 2,T2,,500,1100'])
        l1, l2 = b.line_ids.sorted('sequence')
        for l in (l1, l2):
            l.with_user(self.officer).action_verify_partner(self.pa, 'checked')
        self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': l1.id, 'invoice_id': inv.id, 'amount': 600})
        self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': l2.id, 'invoice_id': inv.id, 'amount': 400})
        self.approve_post(b)
        self.assertEqual(inv.payment_state, 'paid')
        # the 100 not allocated stays on suspense, unreconciled, with the party recorded
        self.assertEqual(l2.statement_line_id.amount_residual, -100)
        self.assertFalse(l2.statement_line_id.is_reconciled)

    def test_11_allocation_validation(self):
        inv = self.invoice(self.pa, 1000)
        other = self.invoice(self.pb, 1000)
        bill = self.invoice(self.pa, 200, 'in_invoice')
        b = self.stage(['01/10/2026,X,,,1000,1000'])
        line = b.line_ids
        line.with_user(self.officer).action_verify_partner(self.pa, 'checked')
        Alloc = self.env['ei.bank.allocation'].with_user(self.officer)
        for inv_, amt in ((other, 100), (inv, 1001), (bill, 100), (inv, 0)):
            with self.assertRaises(UserError):
                Alloc.create({'line_id': line.id, 'invoice_id': inv_.id, 'amount': amt})
        Alloc.create({'line_id': line.id, 'invoice_id': inv.id, 'amount': 600})
        with self.assertRaises(UserError):
            Alloc.create({'line_id': line.id, 'invoice_id': inv.id, 'amount': 600})  # > line amount

    def test_12_payment_settles_vendor_bill(self):
        bill = self.invoice(self.pa, 300, 'in_invoice')
        b = self.stage(['01/10/2026,PAY SUPPLIER,,300,,-300'])
        line = b.line_ids
        line.with_user(self.officer).action_verify_partner(self.pa, 'cheque copy')
        self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': line.id, 'invoice_id': bill.id, 'amount': 300})
        self.approve_post(b)
        self.assertEqual(bill.payment_state, 'paid')

    # --- controls
    def test_13_separation_of_duties(self):
        b = self.full_flow(self.stage(['01/10/2026,DEP,,,5,5']))
        self.officer.group_ids = [Command.link(self.env.ref('ei_bank_operations.group_ei_bank_approver').id)]
        with self.assertRaises(AccessError):
            b.with_user(self.officer).action_approve()  # importer cannot approve
        b.with_user(self.approver).action_approve()
        self.approver.group_ids = [Command.link(self.env.ref('ei_bank_operations.group_ei_bank_poster').id)]
        with self.assertRaises(AccessError):
            b.with_user(self.approver).action_post()  # approver cannot post
        self.officer.group_ids = [Command.link(self.env.ref('ei_bank_operations.group_ei_bank_poster').id)]
        with self.assertRaises(AccessError):
            b.with_user(self.officer).action_post()  # importer cannot post
        b.with_user(self.poster).action_post()
        self.assertEqual(b.state, 'posted')

    def test_14_roles(self):
        with self.assertRaises(AccessError):
            self.Import.with_user(self.poster).import_file(self.journal, 'x.csv', csv('01/10/2026,A,,,1,1'), 0, 1)
        with self.assertRaises(AccessError):
            self.stage(['01/10/2026,DEP,,,5,5']).with_user(self.officer).action_approve()

    def test_15_suggestions_never_allocate(self):
        Alias = self.env['ei.partner.alias'].sudo()
        Alias.create({'partner_id': self.pa.id, 'alias': 'ARIF PATANWALA', 'state': 'approved'})
        Alias.create({'partner_id': self.pa.id, 'alias': 'SHARED NAME', 'state': 'approved'})
        Alias.create({'partner_id': self.pb.id, 'alias': 'SHARED NAME', 'state': 'approved'})
        Alias.create({'partner_id': self.pb.id, 'alias': 'MAYBE TRADER', 'state': 'proposed'})
        b = self.stage(['01/10/2026,RAAST ARIF PATANWALA KHI,,,10,10', '01/10/2026,Shared   name co,,,20,30',
                        '01/10/2026,maybe trader,,,30,60', '01/10/2026,NOBODY,,,40,100'])
        b.action_suggest()
        l = b.line_ids.sorted('sequence')
        self.assertEqual((l[0].suggested_partner_id, l[0].confidence), (self.pa, 0.9))
        self.assertFalse(l[1].suggested_partner_id)
        self.assertIn('Ambiguous', l[1].match_note)
        self.assertEqual((l[2].suggested_partner_id, l[2].confidence), (self.pb, 0.4))
        self.assertEqual(l[3].state, 'new')
        self.assertFalse(l.mapped('partner_id'))  # nothing verified automatically
        with self.assertRaises(UserError):  # cannot approve with unresolved lines
            b.with_user(self.approver).action_approve()
        # an approved-alias suggestion can be verified without extra note; a weak one needs evidence
        l[0].with_user(self.officer).action_verify_partner(self.pa)
        with self.assertRaises(UserError):
            l[2].with_user(self.officer).action_verify_partner(self.pb)

    def test_16_amount_matches_single_open_invoice(self):
        self.invoice(self.pb, 777)
        b = self.stage(['01/10/2026,UNLABELLED,,,777,777'])
        b.action_suggest()
        self.assertEqual((b.line_ids.suggested_partner_id, b.line_ids.confidence), (self.pb, 0.5))
        self.assertEqual(b.line_ids.state, 'proposed')

    def test_17_daily_close(self):
        b = self.stage(['01/10/2026,A,,,10,10', '01/10/2026,B,,,20,30'])
        close = self.env['ei.bank.daily.close'].with_user(self.approver).create({'journal_id': self.journal.id})
        self.assertEqual((close.n_imported, close.n_unmatched, close.n_processed), (2, 2, 0))
        with self.assertRaises(UserError):
            close.action_close()
        self.full_flow(b)
        self.approve_post(b)
        close.invalidate_recordset()
        self.assertEqual((close.n_processed, close.n_unmatched, close.n_reviewed), (2, 0, 2))
        close.with_user(self.approver).action_close()
        self.assertEqual(close.state, 'closed')
        self.assertIn('unidentified-in-suspense 2', close.snapshot)

    def test_18_reject_batch_locks_lines(self):
        b = self.stage(['01/10/2026,A,,,10,10'])
        b.with_user(self.approver).action_reject()
        self.assertEqual(b.line_ids.state, 'rejected')
        with self.assertRaises(UserError):
            b.line_ids.with_user(self.officer).action_verify_partner(self.pa, 'x')
        # the same file may be re-uploaded after rejection
        b2 = self.stage(['01/10/2026,A,,,10,10'])
        self.assertEqual(b2.state, 'validated')

    def test_19_non_bank_journal_refused(self):
        with self.assertRaises(UserError):
            self.Import.with_user(self.officer).import_file(self.company_data['default_journal_cash'], 'x.csv',
                                                            csv('01/10/2026,A,,,1,1'), 0, 1)

    # --- allocation hygiene found while building the matching screen (AUDIT D19, D20)
    def test_20_two_bank_lines_cannot_claim_the_same_money_on_one_invoice(self):
        inv = self.invoice(self.pa, 1000)
        b = self.stage(['01/10/2026,ARIF 1,T1,,1000,1000', '02/10/2026,ARIF 2,T2,,1000,2000'])
        l1, l2 = b.line_ids.sorted('sequence')
        for l in (l1, l2):
            l.with_user(self.officer).action_verify_partner(self.pa, 'checked')
        Alloc = self.env['ei.bank.allocation'].with_user(self.officer)
        Alloc.create({'line_id': l1.id, 'invoice_id': inv.id, 'amount': 600})
        with self.assertRaises(UserError) as cm:
            Alloc.create({'line_id': l2.id, 'invoice_id': inv.id, 'amount': 500})     # only 400 is left to claim
        self.assertIn('another bank line', str(cm.exception))
        Alloc.create({'line_id': l2.id, 'invoice_id': inv.id, 'amount': 400})
        self.approve_post(b)
        self.assertEqual(inv.payment_state, 'paid')
        self.assertAlmostEqual(inv.amount_residual, 0)

    def test_21_officer_can_take_an_allocation_back_until_the_line_is_posted(self):
        inv = self.invoice(self.pa, 1000)
        b = self.stage(['01/10/2026,ARIF,T1,,1000,1000'])
        line = b.line_ids
        line.with_user(self.officer).action_verify_partner(self.pa, 'checked')
        alloc = self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': line.id, 'invoice_id': inv.id, 'amount': 1000})
        alloc.unlink()                                            # the form's trash-can icon must work for the person who made it
        self.assertFalse(line.allocation_ids)
        alloc = self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': line.id, 'invoice_id': inv.id, 'amount': 1000})
        self.approve_post(b)
        with self.assertRaises((UserError, AccessError)):
            alloc.with_user(self.officer).unlink()                # but never after posting: the books already used it
        self.assertEqual(inv.payment_state, 'paid')

    def test_22_a_new_party_cannot_inherit_the_old_partys_allocations(self):
        inv = self.invoice(self.pa, 1000)
        b = self.stage(['01/10/2026,ARIF,T1,,1000,1000'])
        line = b.line_ids
        line.with_user(self.officer).action_verify_partner(self.pa, 'checked')
        self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': line.id, 'invoice_id': inv.id, 'amount': 1000})
        with self.assertRaises(UserError):
            line.with_user(self.officer).action_verify_partner(self.pb, 'changed my mind')
        self.assertEqual(line.partner_id, self.pa)
        line.allocation_ids.with_user(self.officer).unlink()
        line.with_user(self.officer).action_verify_partner(self.pb, 'now it is B')
        self.assertEqual(line.partner_id, self.pb)

    def test_23_allocation_changes_are_written_on_the_line(self):
        inv = self.invoice(self.pa, 1000)
        b = self.stage(['01/10/2026,ARIF,T1,,1000,1000'])
        line = b.line_ids
        line.with_user(self.officer).action_verify_partner(self.pa, 'checked')
        alloc = self.env['ei.bank.allocation'].with_user(self.officer).create({'line_id': line.id, 'invoice_id': inv.id, 'amount': 400})
        alloc.unlink()
        text = ' '.join(line.message_ids.mapped('body'))
        self.assertIn('Allocated by', text)
        self.assertIn('Allocation removed by', text)
