from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.ei_bank_operations.tests.test_banking import csv
from odoo.addons.ei_matching.models.matching import EiMatching


@tagged('post_install', '-at_install', 'ei')
class TestMatching(AccountTestInvoicingCommon):
    """The matching screen is a front for the bank rules. These tests drive it as real role users and check that it
    decides nothing by itself, labels suggestions as suggestions, and reaches exactly the same books as the old forms."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        g = lambda x: cls.env.ref(x).id
        mk = lambda login, *groups: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([g(x) for x in groups])]})
        cls.officer = mk('m_off', 'ei_bank_operations.group_ei_bank_officer')
        cls.officer2 = mk('m_off2', 'ei_bank_operations.group_ei_bank_officer')
        cls.approver = mk('m_app', 'ei_bank_operations.group_ei_bank_approver')
        cls.poster = mk('m_post', 'ei_bank_operations.group_ei_bank_poster')
        cls.plain = mk('m_plain', 'ei_legacy_master.group_ei_user')
        cls.journal = cls.company_data['default_journal_bank']
        cls.pa, cls.pb = cls.partner_a, cls.partner_b
        cls.Import = cls.env['ei.bank.import']

    # ------------------------------------------------------------------ fixtures
    def M(self, user=None):
        return self.env['ei.matching'].with_user(user or self.officer)

    def invoice(self, partner, amount, due='2026-10-10', move_type='out_invoice'):
        inv = self.env['account.move'].create({
            'move_type': move_type, 'partner_id': partner.id, 'invoice_date': '2026-10-01', 'invoice_date_due': due,
            'invoice_line_ids': [Command.create({'name': 'steel', 'quantity': 1, 'price_unit': amount, 'tax_ids': [Command.set([])]})]})
        inv.action_post()
        return inv

    def stage(self, rows, opening=0, name='m.csv'):
        total = sum(float(r.split(',')[4] or 0) - float(r.split(',')[3] or 0) for r in rows)
        return self.Import.with_user(self.officer).import_file(self.journal, name, csv(*rows), opening, opening + total)

    def alias(self, partner, text, approved=True):
        a = self.env['ei.partner.alias'].sudo().create({'partner_id': partner.id, 'alias': text})
        if approved:
            a.with_user(self.approver).action_approve()
        return a

    def one(self, batch, seq=1):
        return batch.line_ids.filtered(lambda l: l.sequence == seq)

    def items(self, tab='check', user=None, **kw):
        return self.M(user).queue(tab, **kw)['items']

    # ------------------------------------------------------------------ the queue
    def test_01_tabs_count_the_right_lines_and_hide_locked_statements(self):
        self.alias(self.pa, 'ARIF TRADERS')
        b = self.stage(['01/10/2026,RAAST FROM ARIF TRADERS,T1,,1000,1000', '02/10/2026,UNKNOWN DEPOSIT,,,500,1500', '03/10/2026,CHEQUE 77,,,300,1800'])
        b.with_user(self.officer).action_suggest()
        dup = self.stage(['01/10/2026,RAAST FROM ARIF TRADERS,T1,,1000,1000'], name='again.csv')     # same line, another file
        self.assertEqual(self.one(dup).state, 'duplicate')
        q = self.M().queue('check')
        self.assertEqual({t['key']: t['count'] for t in q['tabs']}, {'check': 3, 'allocate': 0, 'unidentified': 0, 'duplicates': 1})
        self.assertEqual([i['state'] for i in q['items']], ['proposed', 'new', 'new'])           # oldest first
        self.one(b, 2).with_user(self.officer).action_mark_unidentified('nobody knows')
        counts = {t['key']: t['count'] for t in self.M().queue('check')['tabs']}
        self.assertEqual((counts['check'], counts['unidentified']), (2, 1))
        self.assertEqual(len(self.items('duplicates')), 1)
        # once the statement is approved its lines are locked, so they are no longer something to decide
        self.one(b, 1).with_user(self.officer).action_verify_partner(self.pa, 'checked')
        self.one(b, 3).with_user(self.officer).action_mark_unidentified('later')
        b.with_user(self.approver).action_approve()
        self.assertEqual(self.items('check') + self.items('allocate') + self.items('unidentified'), [])

    def test_02_search_finds_words_amounts_and_parties(self):
        self.alias(self.pa, 'ARIF TRADERS')
        b = self.stage(['01/10/2026,RAAST FROM ARIF TRADERS,T1,,1000,1000', '02/10/2026,UNKNOWN DEPOSIT,,,25000.5,26000.5'])
        b.with_user(self.officer).action_suggest()
        by = lambda q: [i['narration'] for i in self.items(q=q)]
        self.assertEqual(by('unknown'), ['UNKNOWN DEPOSIT'])
        self.assertEqual(by('25,000.5'), ['UNKNOWN DEPOSIT'])
        self.assertEqual(by(self.pa.name), ['RAAST FROM ARIF TRADERS'])
        self.assertEqual(by('%'), [])                                   # a wildcard is text, not a pattern
        self.assertEqual(len(by('')), 2)

    def test_03_same_amount_nearby_is_a_warning_not_a_decision(self):
        b = self.stage(['01/10/2026,PAYER ONE,,,50000,50000', '01/10/2026,PAYER TWO,,,50000,100000', '25/10/2026,PAYER THREE,,,50000,150000',
                        '02/10/2026,SMALLER,,,49999,199999'])
        flags = {i['narration']: i['twin'] for i in self.items()}
        self.assertEqual(flags, {'PAYER ONE': True, 'PAYER TWO': True, 'PAYER THREE': False, 'SMALLER': False})
        d = self.M().detail(self.one(b, 1).id)
        self.assertEqual([t['narration'] for t in d['twins']], ['PAYER TWO'])
        self.assertTrue(d['twins'][0]['same_statement'])
        self.assertEqual(self.one(b, 1).state, 'new')                  # a warning only: nothing was changed

    def test_04_put_aside_hides_only_for_me_and_changes_nothing(self):
        b = self.stage(['01/10/2026,A,,,10,10'])
        line = self.one(b)
        res = self.M().defer(line.id, 3)
        self.assertTrue(res['detail']['can']['deferred'])
        self.assertEqual(self.items(), [])
        self.assertEqual(len(self.items(user=self.officer2)), 1)       # a colleague still sees it
        q = self.M().queue('check')
        self.assertEqual(q['deferred'], 1)
        self.assertEqual(len(self.M().queue('check', deferred=True)['items']), 1)
        self.assertEqual(line.state, 'new')
        self.M().undefer(line.id)
        self.assertEqual(len(self.items()), 1)
        with self.assertRaises(UserError):
            self.M().defer(line.id, 2)                                   # only tomorrow / 3 days / a week

    # ------------------------------------------------------------------ who paid
    def test_05_a_suggestion_is_labelled_and_never_confirms_or_allocates(self):
        self.alias(self.pa, 'ARIF TRADERS')
        self.alias(self.pb, 'BASHIR STEEL', approved=False)
        inv = self.invoice(self.pa, 1000)
        b = self.stage(['01/10/2026,RAAST FROM ARIF TRADERS,T1,,1000,1000', '02/10/2026,BASHIR STEEL LTD,,,700,1700'])
        b.with_user(self.officer).action_suggest()
        strong, weak = self.one(b, 1), self.one(b, 2)
        d = self.M().detail(strong.id)
        self.assertEqual((d['suggestion']['kind'], d['suggestion']['needs_note']), ('approved_alias', False))
        self.assertEqual(d['suggestion']['pct'], 90)
        self.assertIsNone(d['party'])                                  # not confirmed
        self.assertTrue(d['preview_party'])
        self.assertFalse(d['can']['allocate'])
        self.assertEqual([o['invoice_id'] for o in d['open_items']], [inv.id])
        self.assertFalse(strong.allocation_ids)
        self.assertEqual(strong.state, 'proposed')
        w = self.M().detail(weak.id)['suggestion']
        self.assertEqual((w['kind'], w['needs_note']), ('proposed_alias', True))
        with self.assertRaises(UserError):                             # a guess needs evidence
            self.M().set_allocations(strong.id, [{'invoice_id': inv.id, 'amount': 1000}])

    def test_06_confirming_follows_the_evidence_rule_of_the_bank_module(self):
        self.alias(self.pa, 'ARIF TRADERS')
        self.alias(self.pb, 'BASHIR STEEL', approved=False)
        b = self.stage(['01/10/2026,RAAST FROM ARIF TRADERS,T1,,1000,1000', '02/10/2026,BASHIR STEEL LTD,,,700,1700'])
        b.with_user(self.officer).action_suggest()
        strong, weak = self.one(b, 1), self.one(b, 2)
        res = self.M().confirm_party(strong.id, self.pa.id)            # an approved alias needs no note
        self.assertEqual(res['detail']['party']['name'], self.pa.name)
        self.assertEqual(res['detail']['party']['by'], self.officer.name)
        with self.assertRaises(UserError):
            self.M().confirm_party(weak.id, self.pb.id)
        with self.assertRaises(UserError):
            self.M().confirm_party(weak.id, self.pb.id, '   ')
        res = self.M().confirm_party(weak.id, self.pb.id, 'slip seen in the payments group')
        self.assertEqual(weak.state, 'verified')
        self.assertIn('slip seen', res['detail']['party']['note'])
        self.assertTrue(any('Party confirmed' in h['text'] for h in res['detail']['history']))

    def test_07_changing_the_party_removes_the_old_partys_allocations_only_when_told(self):
        inv = self.invoice(self.pa, 1000)
        line = self.one(self.stage(['01/10/2026,ARIF,T1,,1000,1000']))
        self.M().confirm_party(line.id, self.pa.id, 'checked')
        self.M().set_allocations(line.id, [{'invoice_id': inv.id, 'amount': 1000}])
        with self.assertRaises(UserError):
            self.M().confirm_party(line.id, self.pb.id, 'changed my mind')
        self.assertEqual((line.partner_id, len(line.allocation_ids)), (self.pa, 1))
        self.M().confirm_party(line.id, self.pb.id, 'it was B', clear_allocations=True)
        self.assertEqual((line.partner_id, len(line.allocation_ids)), (self.pb, 0))

    def test_08_party_search_finds_real_parties(self):
        found = self.M().search_party(self.pa.name[:6])
        self.assertIn(self.pa.id, [r['partner_id'] for r in found])
        self.assertEqual(self.M().search_party('a'), [])               # one letter is not a search

    # ------------------------------------------------------------------ which invoices
    def test_09_allocation_round_trip_with_the_effect_shown_before_posting(self):
        i1, i2 = self.invoice(self.pa, 1000, due='2026-10-05'), self.invoice(self.pa, 500, due='2026-10-20')
        bill = self.invoice(self.pa, 300, move_type='in_invoice')      # a supplier bill: never offered for a receipt
        line = self.one(self.stage(['01/10/2026,ARIF,T1,,1400,1400']))
        self.M().confirm_party(line.id, self.pa.id, 'checked')
        d = self.M().detail(line.id)
        self.assertEqual([o['invoice_id'] for o in d['open_items']], [i1.id, i2.id])      # longest overdue first
        self.assertNotIn(bill.id, [o['invoice_id'] for o in d['open_items']])
        moves_before = self.env['account.move'].search_count([])
        d = self.M().set_allocations(line.id, [{'invoice_id': i1.id, 'amount': 1000}, {'invoice_id': i2.id, 'amount': 300}, {'invoice_id': bill.id, 'amount': 0}])['detail']
        self.assertEqual((d['allocated'], d['remaining']), (1300, 100))
        kinds = [r['kind'] for r in d['impact']]
        self.assertEqual(kinds, ['bank', 'party', 'party', 'suspense'])
        self.assertTrue(d['impact'][1]['settled'] and not d['impact'][2]['settled'])
        self.assertIn('stays unallocated', d['impact'][3]['plain'])
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)       # saving an allocation posts nothing
        self.assertEqual(i1.payment_state, 'not_paid')
        # replace: take one back, change the other
        d = self.M().set_allocations(line.id, [{'invoice_id': i2.id, 'amount': 500}])['detail']
        self.assertEqual([(a['invoice_id'], a['amount']) for a in d['allocations']], [(i2.id, 500)])
        d = self.M().set_allocations(line.id, [])['detail']
        self.assertEqual((d['allocations'], d['remaining']), ([], 1400))
        self.assertTrue(any('Allocation cleared' in h['text'] for h in d['history']))

    def test_10_a_bad_allocation_is_refused_and_leaves_the_saved_one_alone(self):
        i1, other = self.invoice(self.pa, 1000), self.invoice(self.pb, 1000)
        line = self.one(self.stage(['01/10/2026,ARIF,T1,,1000,1000']))
        self.M().confirm_party(line.id, self.pa.id, 'checked')
        self.M().set_allocations(line.id, [{'invoice_id': i1.id, 'amount': 600}])
        for bad in ([{'invoice_id': other.id, 'amount': 100}],              # another party's invoice
                    [{'invoice_id': i1.id, 'amount': 1001}],                # more than is open
                    [{'invoice_id': i1.id, 'amount': 600}, {'invoice_id': i1.id, 'amount': 600}]):   # more than the payment
            with self.assertRaises(UserError):
                self.M().set_allocations(line.id, bad)
            self.assertEqual(line.allocation_ids.mapped('amount'), [600])   # the refused save changed nothing
        with self.assertRaises(UserError):
            self.M(self.officer2).set_allocations(self.one(self.stage(['02/10/2026,NOBODY,,,5,1005'], opening=1000, name='n.csv')).id,
                                                  [{'invoice_id': i1.id, 'amount': 5}])    # an unconfirmed line cannot be allocated

    def test_11_money_claimed_by_another_line_is_shown_and_cannot_be_claimed_again(self):
        inv = self.invoice(self.pa, 1000)
        b = self.stage(['01/10/2026,ARIF 1,T1,,600,600', '02/10/2026,ARIF 2,T2,,600,1200'])
        l1, l2 = self.one(b, 1), self.one(b, 2)
        for l in (l1, l2):
            self.M().confirm_party(l.id, self.pa.id, 'checked')
        self.M().set_allocations(l1.id, [{'invoice_id': inv.id, 'amount': 600}])
        item = self.M().detail(l2.id)['open_items'][0]
        self.assertEqual((item['claimed'], item['available']), (600, 400))
        with self.assertRaises(UserError) as cm:
            self.M().set_allocations(l2.id, [{'invoice_id': inv.id, 'amount': 500}])
        self.assertIn('another bank line', str(cm.exception))
        self.M().set_allocations(l2.id, [{'invoice_id': inv.id, 'amount': 400}])

    def test_12_the_proposal_is_exact_when_it_can_be_and_never_saves(self):
        a, b_, c = (self.invoice(self.pa, 300, due='2026-10-01'), self.invoice(self.pa, 200, due='2026-10-02'), self.invoice(self.pa, 700, due='2026-10-03'))
        line = self.one(self.stage(['01/10/2026,ARIF,T1,,500,500']))
        with self.assertRaises(UserError):                              # only for a confirmed party
            self.M().suggest_allocation(line.id)
        self.M().confirm_party(line.id, self.pa.id, 'checked')
        p = self.M().suggest_allocation(line.id)
        self.assertTrue(p['sure'])
        self.assertEqual({i['invoice_id'] for i in p['items']}, {a.id, b_.id})      # 300 + 200 add up exactly
        self.assertIn('exactly', p['why'])
        self.assertFalse(line.allocation_ids)                          # a proposal writes nothing
        # nothing matches exactly: oldest first, never more than the payment or the open amount
        line2 = self.one(self.stage(['02/10/2026,ARIF,T2,,600,1100'], opening=500, name='x.csv'))
        self.M().confirm_party(line2.id, self.pa.id, 'checked')
        p = self.M().suggest_allocation(line2.id)
        self.assertFalse(p['sure'])
        self.assertEqual([(i['invoice_id'], i['amount']) for i in p['items']], [(a.id, 300), (b_.id, 200), (c.id, 100)])
        self.assertFalse(line2.allocation_ids)

    def test_13_several_exact_answers_are_not_guessed(self):
        x, y = self.invoice(self.pa, 100, due='2026-10-01'), self.invoice(self.pa, 100, due='2026-10-02')
        line = self.one(self.stage(['01/10/2026,ARIF,T1,,100,100']))
        self.M().confirm_party(line.id, self.pa.id, 'checked')
        p = self.M().suggest_allocation(line.id)
        self.assertFalse(p['sure'])
        self.assertEqual([i['invoice_id'] for i in p['items']], [x.id])  # the older one, but flagged as a choice
        self.assertIn('choose', p['why'])

    # ------------------------------------------------------------------ the other decisions
    def test_14_unidentified_reject_and_ask(self):
        inv = self.invoice(self.pa, 100)
        b = self.stage(['01/10/2026,A,,,100,100', '02/10/2026,B,,,10,110', '03/10/2026,C,,,20,130'])
        l1, l2, l3 = (self.one(b, n) for n in (1, 2, 3))
        self.M().confirm_party(l1.id, self.pa.id, 'checked')
        self.M().set_allocations(l1.id, [{'invoice_id': inv.id, 'amount': 100}])
        with self.assertRaises(UserError):                                # allocations must be taken back first
            self.M().mark_unidentified(l1.id, 'oops')
        self.M().mark_unidentified(l1.id, 'oops, it was not them', clear_allocations=True)
        self.assertEqual((l1.state, len(l1.allocation_ids)), ('unidentified', 0))
        with self.assertRaises(UserError):
            self.M().reject(l2.id, '  ')
        self.assertEqual(self.M().reject(l2.id, 'not ours')['detail']['line']['state'], 'rejected')
        with self.assertRaises(UserError):
            self.M().ask_evidence(l3.id, 'ok')                            # too short to mean anything
        with self.assertRaises(UserError):
            self.M().ask_evidence(l3.id, 'Please send the slip', user_id=self.plain.id)   # cannot open the line
        res = self.M().ask_evidence(l3.id, 'Please send the payment slip', user_id=self.officer2.id)
        self.assertTrue(any('Evidence requested' in h['text'] for h in res['detail']['history']))
        act = self.env['mail.activity'].sudo().search([('res_model', '=', 'ei.bank.import.line'), ('res_id', '=', l3.id)])
        self.assertEqual(act.user_id, self.officer2)
        self.assertEqual(l3.state, 'new')                                 # asking changes nothing else

    def test_15_a_repeat_shows_what_it_repeats_and_can_be_rejected(self):
        self.stage(['01/10/2026,SAME,T1,,100,100'])
        dup = self.one(self.stage(['01/10/2026,SAME,T1,,100,100', '02/10/2026,OTHER,,,5,105'], name='b.csv'))
        d = self.M().detail(dup.id)
        self.assertEqual(d['line']['state'], 'duplicate')
        self.assertTrue(d['duplicate_of'])
        self.assertFalse(d['can']['confirm'])
        self.M().reject(dup.id, 'Duplicate of the line in the first file')
        self.assertEqual(self.items('duplicates'), [])

    # ------------------------------------------------------------------ who may do what
    def test_16_only_bank_officers_decide_and_others_can_only_look(self):
        line = self.one(self.stage(['01/10/2026,A,,,100,100']))
        d = self.M(self.approver).detail(line.id)                        # a bank approver may look
        self.assertFalse(any(d['can'].values()))
        self.assertFalse(self.M(self.approver).queue('check')['can_review'])
        for call in (lambda M: M.confirm_party(line.id, self.pa.id, 'x'), lambda M: M.mark_unidentified(line.id),
                     lambda M: M.reject(line.id, 'x'), lambda M: M.set_allocations(line.id, []), lambda M: M.defer(line.id, 1),
                     lambda M: M.ask_evidence(line.id, 'please check this')):
            with self.assertRaises(AccessError):
                call(self.M(self.approver))
        self.assertEqual(self.M(self.plain).queue('check')['items'], [])  # no bank role: nothing to see
        with self.assertRaises(AccessError):
            self.M(self.plain).detail(line.id)
        self.assertEqual(line.state, 'new')

    def test_17_the_screen_cannot_approve_or_post(self):
        public = [n for n, v in vars(EiMatching).items() if not n.startswith('_') and callable(v)]
        self.assertIn('confirm_party', public)
        self.assertFalse([n for n in public if 'approve' in n or 'post' in n])

    # ------------------------------------------------------------------ the whole way to the books
    def test_18_what_the_preview_says_is_what_posting_does(self):
        i1, i2 = self.invoice(self.pa, 1000, due='2026-10-05'), self.invoice(self.pa, 500, due='2026-10-20')
        b = self.stage(['01/10/2026,ARIF PAYMENT,T1,,1400,1400'])
        line = self.one(b)
        self.M().confirm_party(line.id, self.pa.id, 'checked by bank call')
        self.M().set_allocations(line.id, [{'invoice_id': i1.id, 'amount': 1000}, {'invoice_id': i2.id, 'amount': 300}])
        d = self.M().detail(line.id)
        said = {r['invoice']: r['settled'] for r in d['impact'] if r['kind'] == 'party'}
        left = d['remaining']
        # the same people the bank module demands, not the officer who did the matching
        b.with_user(self.approver).action_approve()
        b.with_user(self.poster).action_post()
        self.assertEqual((i1.payment_state == 'paid', i2.payment_state == 'paid'), (said[i1.name], said[i2.name]))
        self.assertAlmostEqual(i2.amount_residual, 200)
        st = line.statement_line_id
        self.assertAlmostEqual(abs(st.amount_residual), left)             # the preview's "stays unallocated" is what is left
        self.assertEqual(line.state, 'posted')
        self.assertEqual(self.items('allocate'), [])

    def test_19_the_officer_who_matched_cannot_approve_the_statement(self):
        b = self.stage(['01/10/2026,A,,,100,100'])
        self.M().mark_unidentified(self.one(b).id, 'nobody knows')
        self.officer.group_ids = [Command.link(self.env.ref('ei_bank_operations.group_ei_bank_approver').id)]
        with self.assertRaises(AccessError):
            b.with_user(self.officer).action_approve()

    def test_20_home_task_opens_the_screen_on_that_line_for_officers_only(self):
        line = self.one(self.stage(['01/10/2026,A,,,100,100']))
        act = self.env['ei.work'].with_user(self.officer).open_task('ei.bank.import.line', line.id)
        self.assertEqual((act['type'], act['tag'], act['params']), ('ir.actions.client', 'ei_matching', {'line_id': line.id}))
        act = self.env['ei.work'].with_user(self.approver).open_task('ei.bank.import.line', line.id)
        self.assertEqual((act['type'], act['res_model']), ('ir.actions.act_window', 'ei.bank.import.line'))   # no decision rights: the plain form
