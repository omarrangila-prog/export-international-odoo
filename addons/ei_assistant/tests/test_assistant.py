"""Ask runs on the SAME world the end-to-end journey builds (real role users, real records, no mocks): contract 100 MTL -> DA-5501
10 MTL -> daily order -> 4 MTL lifted -> supplier bill 800,000 (unpaid) -> customer invoice 840,000 (paid by a bank receipt)."""
import os
import re
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools.misc import format_amount

from odoo.addons.ei_assistant.models import assistant as engine
from odoo.addons.ei_management_dashboard.tests.test_journey import TestJourney

# every phrasing below must be understood as the type of question named next to it (None = no question type matches)
ROUTES = (
    ('What is waiting for me?', 'work'), ("what's waiting for me", 'work'), ('my tasks please', 'work'), ('What should I do today', 'work'),
    ('what do I need to approve?', 'work'), ('anything assigned to me', 'work'), ('show my to do list', 'work'),
    ('Is anything wrong?', 'attention'), ("what's wrong", 'attention'), ('any problems today', 'attention'), ('what needs attention', 'attention'),
    ('Who owes us money?', 'owed_to_us'), ('who owes us', 'owed_to_us'), ('show receivables', 'owed_to_us'), ('outstanding invoices', 'owed_to_us'),
    ('unpaid customer invoices', 'owed_to_us'), ('how much do customers owe', 'owed_to_us'),
    ('What is overdue?', 'overdue'), ('which invoices are past due', 'overdue'), ('late payments', 'overdue'), ('show ageing', 'overdue'),
    ('What do we owe our suppliers?', 'we_owe'), ('payables', 'we_owe'), ('how much do we owe', 'we_owe'), ('unpaid supplier bills', 'we_owe'),
    ('How much is left to lift?', 'lift'), ('remaining quantity', 'lift'), ('mtl left', 'lift'), ('what is still to lift', 'lift'), ('pending lifting', 'lift'),
    ('How many bank payments need checking?', 'bank_todo'), ('unmatched bank lines', 'bank_todo'), ('who paid us', 'bank_todo'), ('any duplicate payments', 'bank_todo'),
    ('What are the bank balances?', 'bank_balance'), ('how much money is in the bank', 'bank_balance'), ('bank balance', 'bank_balance'),
    ('Give me the key figures', 'kpis'), ('how are we doing', 'kpis'), ('overview', 'kpis'), ('summary please', 'kpis'),
    ('help', 'help'), ('what can you do?', 'help'),
    # a request to DO something is refused, a question ABOUT doing it is answered
    ('approve the invoice', 'refuse'), ('Please post the bank statement', 'refuse'), ('can you pay this bill', 'refuse'), ('delete the contract', 'refuse'),
    ('send a reminder to the customer', 'refuse'), ('mark it as paid', 'refuse'),
    # no question type: the words are looked up as a name, a number or an old code
    ('Rehman Traders', None), ('4.20', None), ('CT/2026/0001', None), ('hello there', None), ('', None),
)


@tagged('post_install', '-at_install', 'ei')
class TestAssistant(TestJourney):
    """Re-uses the journey fixture; the journey's own tests run in their own class, not here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.today()
        cls.slow = cls.env['res.partner'].create({'name': 'Slow Payer Traders'})
        inv = cls.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': cls.slow.id, 'invoice_date': today - timedelta(days=60),
            'invoice_date_due': today - timedelta(days=40),
            'invoice_line_ids': [Command.create({'name': 'steel', 'quantity': 1, 'price_unit': 250000, 'tax_ids': [Command.set([])]})]})
        inv.action_post()
        cls.slow_invoice = inv
        cls.future = cls.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': cls.slow.id, 'invoice_date': today, 'invoice_date_due': today + timedelta(days=30),
            'invoice_line_ids': [Command.create({'name': 'steel', 'quantity': 1, 'price_unit': 50000, 'tax_ids': [Command.set([])]})]})
        cls.future.action_post()
        cls.alpha = cls.env['res.partner'].create({'name': 'Twin Alpha Steel'})
        cls.beta = cls.env['res.partner'].create({'name': 'Twin Beta Steel'})
        cls.plain = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'a_plain', 'login': 'a_plain', 'group_ids': [Command.set([cls.env.ref('base.group_user').id])]})

    def A(self, user=None):
        return self.env['ei.assistant'].with_user(user or self.ceo)

    def ask(self, text, user=None):
        return self.A(user).ask(text)

    def money(self, amount):
        return format_amount(self.env, amount, self.co.currency_id)

    @staticmethod
    def figures(reply):
        return {f['label']: f for b in reply['blocks'] if b['type'] == 'figures' for f in b['items']}

    @staticmethod
    def table(reply):
        return next((b for b in reply['blocks'] if b['type'] == 'table'), None)

    def dash(self):
        return self.env['ei.dashboard'].with_user(self.ceo).create({})      # as on Home: "today" is today

    # ------------------------------------------------------------------ a01 what it understands
    def test_a01_every_phrasing_goes_to_the_right_kind_of_question(self):
        wrong = [(text, want, engine.route(text)) for text, want in ROUTES if engine.route(text) != want]
        self.assertEqual(wrong, [])

    def test_a02_a_question_about_approving_is_not_an_order_to_approve(self):
        self.assertEqual(engine.route('what is waiting for me to approve'), 'work')
        self.assertEqual(engine.route('who approved this contract'), None)

    # ------------------------------------------------------------------ a03 the figures are the product's figures
    def test_a03_money_answers_equal_the_management_dashboard(self):
        d = self.dash()
        owed = self.ask('Who owes us money?')
        self.assertEqual(owed['kind'], 'answer')
        self.assertEqual(self.figures(owed)['Customers owe us']['value'], self.money(d.ar_open))
        self.assertEqual(d.ar_open, 300000)                              # 250,000 overdue + 50,000 not yet due; the 840,000 invoice is paid
        t = self.table(owed)
        self.assertEqual([r['cells'][0] for r in t['rows']], ['Slow Payer Traders'])
        self.assertEqual(t['rows'][0]['cells'][1], self.money(300000))
        late = self.ask('What is overdue?')
        self.assertEqual(self.figures(late)['Overdue in total']['value'], self.money(d.ar_open - d.aging_current))
        self.assertEqual(self.figures(late)['Overdue in total']['value'], self.money(250000))
        row = self.table(late)['rows'][0]['cells']
        self.assertEqual((row[0], row[1], row[4]), (self.slow_invoice.name, 'Slow Payer Traders', '40'))
        self.assertNotIn(self.future.name, [r['cells'][0] for r in self.table(late)['rows']])    # not yet due: not listed
        we = self.ask('What do we owe our suppliers?')
        self.assertEqual(self.figures(we)['We owe suppliers']['value'], self.money(d.ap_open))
        self.assertEqual(d.ap_open, 800000)
        self.assertEqual(self.table(we)['rows'][0]['cells'][0], self.parent.name)

    def test_a04_asking_about_one_party_gives_that_partys_figures(self):
        r = self.ask('How much does Slow Payer Traders owe us?')
        self.assertEqual(r['title'], 'What Slow Payer Traders owes us')
        f = self.figures(r)
        self.assertEqual(f['Slow Payer Traders owes us']['value'], self.money(300000))
        self.assertEqual(f['Of which overdue']['value'], self.money(250000))
        self.assertEqual(self.figures(self.ask('what do we owe Parent Steel'))['We owe Parent Steel Ltd']['value'], self.money(800000))

    def test_a05_money_is_for_finance_management_and_the_auditor_only(self):
        for user in (self.officer, self.maker, self.cashclerk, self.dispatch):
            for q in ('Who owes us money?', 'What is overdue?', 'What do we owe our suppliers?'):
                r = self.ask(q, user)
                self.assertEqual(r['kind'], 'denied', (user.login, q))
                self.assertNotIn('300,000', str(r))
        self.assertEqual(self.ask('Who owes us money?', self.bapprover)['kind'], 'answer')        # a bank approver is a finance role
        self.assertEqual(self.ask('Tell me about Slow Payer Traders', self.maker)['kind'], 'answer')
        text = str(self.ask('Tell me about Slow Payer Traders', self.maker)['blocks'])
        self.assertNotIn('300,000', text)                                  # the party page hides the ledger from an operator
        self.assertIn('Not shown to your role', text)

    # ------------------------------------------------------------------ a06 parties, documents, old codes
    def test_a06_party_summary_equals_party_360(self):
        want = self.env['ei.party360'].with_user(self.ceo).get_data(self.customer.id)
        r = self.A().ask_party(self.customer.id)
        self.assertEqual((r['kind'], r['title']), ('answer', self.customer.name))
        shown = {f['label']: f['value'] for f in self.figures(r).values()}
        for m in [m for m in want['metrics'] if m['count']][:8]:
            self.assertEqual(shown[m['label']], m['text'], m['label'])
        self.assertEqual(shown['Still to lift'], '6.000 MTL')
        self.assertTrue(any(s['kind'] == 'party' and s['partner_id'] == self.customer.id for s in r['sources']))
        self.assertEqual(self.ask(self.customer.name)['title'], self.customer.name)     # a name on its own is enough

    def test_a07_two_parties_fit_so_it_asks_which(self):
        r = self.ask('Twin')
        self.assertEqual(r['kind'], 'choose')
        self.assertEqual({o['party_id'] for o in r['options']}, {self.alpha.id, self.beta.id})
        picked = self.A().ask_party(self.alpha.id)
        self.assertEqual(picked['title'], 'Twin Alpha Steel')

    def test_a08_a_document_number_finds_exactly_that_record(self):
        r = self.ask('what is the status of %s' % self.contract.name)
        self.assertEqual((r['kind'], r['title']), ('answer', self.contract.name))
        self.assertIn({'kind': 'record', 'model': 'ei.contract', 'res_id': self.contract.id, 'label': self.contract.name}, r['sources'])
        r = self.ask('Where is DA-5501?')
        self.assertEqual(r['title'], 'DA-5501')
        self.assertEqual(self.ask('DA-55')['kind'], 'unknown')           # a number is matched exactly, never by similarity

    def test_a09_old_codes_are_exact_text(self):
        r = self.ask('what is old code 1.03')
        self.assertEqual(r['kind'], 'answer')
        self.assertIn('1.03', r['blocks'][0]['items'][0]['text'])
        self.assertEqual(r['blocks'][0]['items'][0]['src2'], 1)          # and it leads to the party it is linked to
        miss = self.ask('code 1.3')
        self.assertEqual(miss['kind'], 'unknown')
        self.assertIn('no old code 1.3', miss['blocks'][0]['text'])

    def test_a10_unknown_words_say_so_and_offer_questions_that_work(self):
        r = self.ask('Zzzz Qqqq')
        self.assertEqual(r['kind'], 'unknown')
        self.assertIn('did not understand', r['title'])
        self.assertTrue(r['suggestions'])
        self.assertEqual(self.ask('')['kind'], 'unknown')
        self.assertEqual(self.ask('x')['kind'], 'unknown')
        arabic = self.ask('کتنا بقایا ہے')
        self.assertEqual(arabic['kind'], 'unknown')
        self.assertIn('Urdu', arabic['blocks'][0]['text'])

    # ------------------------------------------------------------------ a11 material and bank
    def test_a11_left_to_lift_equals_the_journey_and_party_360(self):
        r = self.ask('How much is left to lift?')
        self.assertEqual(self.figures(r)['Still to lift in total']['value'], '6.000 MTL')
        self.assertEqual(self.table(r)['rows'][0]['cells'][0], 'DA-5501')
        self.assertEqual(self.table(r)['rows'][0]['cells'][3], '6.000')
        one = self.ask('how much is left to lift on DA-5501', self.maker)
        self.assertEqual(one['title'], 'Still to lift on DA-5501')
        self.assertEqual(self.figures(one)['Still to lift']['value'], '6.000 MTL')
        party = self.ask('how much is left to lift for %s' % self.customer.name)
        self.assertEqual(self.figures(party)['Still to lift']['value'], '6.000 MTL')

    def test_a12_bank_payments_equal_the_matching_screen(self):
        csv = ("Date,Description,Reference,Debit,Credit,Balance\n12/10/2026,UNKNOWN A,,,500,500\n13/10/2026,UNKNOWN B,,,700,1200\n").encode()
        self.env['ei.bank.import'].with_user(self.officer).import_file(self.bank, 'ask.csv', csv, 840000, 841200)
        tabs = {t['key']: t['count'] for t in self.env['ei.matching'].with_user(self.officer).queue('check')['tabs']}
        r = self.ask('How many bank payments need checking?', self.officer)
        f = self.figures(r)
        self.assertEqual(f['To check']['value'], str(tabs['check']))
        self.assertEqual(tabs['check'], 2)
        self.assertEqual((f['Unidentified']['value'], f['Duplicates']['value']), (str(tabs['unidentified']), str(tabs['duplicates'])))
        self.assertIn({'kind': 'action', 'key': 'matching', 'label': 'Match bank payments'}, r['sources'])
        self.assertEqual(self.ask('How many bank payments need checking?', self.maker)['kind'], 'denied')   # no bank role
        bal = self.ask('What are the bank balances?', self.officer)
        self.assertEqual(bal['kind'], 'answer')
        row = next(r['cells'] for r in self.table(bal)['rows'] if r['cells'][0] == self.bank.name)
        self.assertEqual(row[1], self.money(self.bank._ei_ledger_balance(fields.Date.today())))

    def test_a13_what_is_waiting_for_me_is_my_work(self):
        csv = ("Date,Description,Reference,Debit,Credit,Balance\n12/10/2026,UNKNOWN C,,,500,500\n").encode()
        self.env['ei.bank.import'].with_user(self.officer).import_file(self.bank, 'work.csv', csv, 840000, 840500)
        mine = [t for t in self.env['ei.work'].with_user(self.officer).tasks()['items'] if t['can_act'] and not t['view_only']]
        r = self.ask('What is waiting for me?', self.officer)
        t = self.table(r)
        self.assertEqual(len(t['rows']), min(len(mine), engine.PER_TABLE))
        self.assertTrue(len(mine) >= 1)
        self.assertTrue(any(s['kind'] == 'task' for s in r['sources']))
        ceo = self.ask('What is waiting for me?', self.ceo)               # management oversees, nothing for the CEO to do
        self.assertIn('Nothing is waiting', ceo['blocks'][0]['text'])

    def test_a14_attention_and_key_figures_are_home(self):
        k = self.ask('Give me the key figures')
        home = self.env['ei.home'].with_user(self.ceo)
        profile, _role = home._profile()
        want = {x['label']: x['value'] for x in home._kpis(profile, home._dash())}
        got = {f['label']: f['value'] for f in self.figures(k).values()}
        self.assertEqual(got, want)
        self.assertEqual(self.ask('Is anything wrong?')['kind'], 'answer')

    # ------------------------------------------------------------------ a15 it can only read
    def test_a15_a_request_to_change_something_is_refused_and_nothing_changes(self):
        models = ['account.move', 'account.move.line', 'ei.bank.import', 'ei.bank.import.line', 'ei.bank.allocation', 'ei.contract', 'ei.da', 'ei.daily.order',
                  'ei.lifting', 'ei.supplier.intake', 'ei.cash.voucher', 'mail.activity', 'mail.message', 'ei.work.snooze', 'res.partner', 'ei.legacy.code']

        def snapshot():
            out = {}
            for m in models:
                recs = self.env[m].sudo().search([])
                out[m] = (len(recs), max(recs.mapped('write_date'), default=None))
            return out
        before = snapshot()
        for user in (self.ceo, self.officer, self.maker, self.bapprover):
            for q in ('approve the invoice', 'Please post the bank statement', 'pay this bill', 'delete the contract', 'send a reminder to the customer', 'mark it as paid'):
                r = self.ask(q, user)
                self.assertEqual(r['kind'], 'refused', q)
                self.assertIn('cannot approve, post, pay', r['blocks'][0]['text'])
        for user in (self.ceo, self.officer, self.maker, self.bapprover):
            for q in self.A(user).starters() + ['help', 'Tell me about Slow Payer Traders', 'DA-5501', 'code 1.03', 'Zzzz']:
                self.ask(q, user)
        self.assertEqual(snapshot(), before)

    def test_a16_every_starter_question_works_for_the_role_that_is_offered_it(self):
        for user in (self.ceo, self.bapprover, self.officer, self.maker, self.cashclerk, self.capprover, self.dispatch, self.invoicer):
            starters = self.A(user).starters()
            self.assertTrue(starters, user.login)
            for q in starters:
                r = self.ask(q, user)
                self.assertEqual(r['kind'], 'answer', (user.login, q, r['kind']))
        self.assertNotIn('Who owes us money?', self.A(self.maker).starters())
        self.assertIn('Who owes us money?', self.A(self.ceo).starters())
        self.assertEqual(self.A(self.plain).starters(), [])

    def test_a17_every_answer_says_how_it_was_worked_out_and_where_from(self):
        for q in ('help', 'What is waiting for me?', 'Is anything wrong?', 'Give me the key figures', 'Who owes us money?', 'What is overdue?', 'What do we owe our suppliers?',
                  'How much is left to lift?', 'How many bank payments need checking?', 'What are the bank balances?', self.customer.name, 'DA-5501', 'code 1.03', 'Zzzz', 'approve it'):
            r = self.ask(q)
            self.assertTrue(r['how'] and r['as_of'] and r['title'], q)
            if r['kind'] == 'answer' and r['intent'] not in ('help',):
                self.assertTrue(r['sources'], q)

    # ------------------------------------------------------------------ a18 sources
    def test_a18_every_source_opens_and_only_known_kinds_exist(self):
        for q in ('Who owes us money?', 'What is overdue?', 'What do we owe our suppliers?', 'Give me the key figures', 'Is anything wrong?', 'How much is left to lift?',
                  self.customer.name, 'DA-5501', 'code 1.03', 'What is waiting for me?'):
            r = self.ask(q)
            for s in r['sources']:
                act = self.A().open_source(s)
                self.assertTrue(act and act.get('type'), (q, s))
        for bad in ({'kind': 'domain', 'model': 'res.users', 'domain': []}, {'kind': 'record', 'model': 'res.users', 'res_id': 1},
                    {'kind': 'action', 'key': 'base.action_res_users'}, {}, {'kind': 'party_metric', 'partner_id': self.customer.id, 'key': 'nope'}):
            with self.assertRaises((AccessError, UserError)):
                self.A().open_source(bad)

    def test_a19_a_source_is_checked_for_the_person_who_opens_it(self):
        with self.assertRaises(AccessError):                              # an operator cannot open a customer invoice
            self.A(self.maker).open_source({'kind': 'record', 'model': 'account.move', 'res_id': self.slow_invoice.id})
        with self.assertRaises((AccessError, UserError)):
            self.A(self.maker).open_source({'kind': 'party_metric', 'partner_id': self.customer.id, 'key': 'f_ar'})

    # ------------------------------------------------------------------ a20 the log and the roles
    def test_a20_questions_are_logged_for_management_only(self):
        Log = self.env['ei.assistant.log']
        self.ask('Who owes us money?', self.ceo)
        self.ask('Zzzz Qqqq', self.maker)
        self.ask('approve the invoice', self.maker)
        self.ask('Who owes us money?', self.maker)
        rows = Log.sudo().search([('user_id', 'in', (self.ceo.id, self.maker.id))], order='id')
        self.assertEqual([(r.user_id.login, r.outcome) for r in rows], [('j_ceo', 'answered'), ('j_maker', 'unknown'), ('j_maker', 'refused'), ('j_maker', 'denied')])
        self.assertEqual(rows[0].intent, 'owed_to_us')
        self.assertEqual(Log.with_user(self.ceo).search_count([]), len(Log.sudo().search([])))
        with self.assertRaises(AccessError):
            Log.with_user(self.maker).search([])
        self.ask('x' * 500, self.ceo)
        self.assertEqual(len(Log.sudo().search([], order='id desc', limit=1).question), 300)

    def test_a21_a_user_with_no_role_is_told_so(self):
        r = self.ask('What is waiting for me?', self.plain)
        self.assertEqual(r['kind'], 'denied')
        self.assertIn('do not have a role', r['blocks'][0]['text'])

    def test_a22_nothing_is_sent_outside_this_server(self):
        folder = os.path.dirname(engine.__file__)
        banned = re.compile(r'\b(requests|urllib|http\.client|httpx|socket|smtplib|openai|anthropic|subprocess|aiohttp)\b')
        for name in os.listdir(folder):
            if name.endswith('.py'):
                with open(os.path.join(folder, name), encoding='utf-8') as fh:
                    self.assertFalse(banned.findall(fh.read()), name)
