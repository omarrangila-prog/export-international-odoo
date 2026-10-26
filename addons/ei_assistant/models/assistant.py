"""Ask: a read-only assistant that looks things up in the company's own records and always shows its sources.

What it is: a rule-based question router. It understands a fixed list of question types (what is waiting for me, who owes us,
what is overdue, how much is left to lift, bank payments to check, tell me about a party, what is the status of a document,
what does an old code mean, is anything wrong) and answers each one by reading real records.

What it is not: a language model. Nothing is sent outside this server, nothing is invented and nothing is guessed. A question it
does not understand is answered "I did not understand that", with the records that match the words and some questions that work.

Guarantees, each covered by a test:
  * READ-ONLY: answering a question never creates or changes a business record (the only thing written is a log line saying
    what was asked and whether it could be answered). A request to do something (approve, post, pay, delete ...) is refused and
    the person is pointed to the screen where a person with the right role does it.
  * Runs as the current user: the same access rules, and the same money rule as the dashboard (ledger figures only for finance,
    management and the auditor), decide what is read.
  * Every answer carries its SOURCES (the records or lists it was worked out from, each one opens) and a plain "how this was
    worked out". Figures are the same ones the rest of the product shows (Home, Party 360); tests compare them.
  * A source is a small token chosen by the server from an allow-list. The client can never ask for an arbitrary list.
"""
import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import format_amount, format_date
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

PER_TABLE = 10
ARABIC_SCRIPT = re.compile('[؀-ۿݐ-ݿ]')
USER_GROUP = 'ei_legacy_master.group_ei_user'
AUDITOR = 'ei_legacy_master.group_ei_auditor'
ACTIONS = {'home': 'ei_ui_theme.action_ei_home', 'matching': 'ei_matching.action_ei_matching'}

# Words that tell the router WHAT is asked; they are removed before the rest is read as a party name.
STOP = set('''tell me about show status of for the a an what whats is are how much many does do owe owed we us they their party
customer customers supplier suppliers balance details information info please who whom which from on with to and my our give find
search look up lookup remaining left lift lifted mtl still pending outstanding unpaid amount invoice invoices bills payment payments
overdue late anything everything all any more most top list display see check need needs want would like can could you i it this
that there here have has had been be was were will shall should may might get got money material quantity order orders delivery
advice advices contract contracts old code codes'''.split())

# A request to DO something. Matched only at the start (after polite words): "what is waiting for me to approve" is a question.
COMMAND = re.compile(
    r'^(?:please\s+|kindly\s+|can you\s+|could you\s+|would you\s+|i want (?:you )?to\s+|go ahead and\s+|just\s+|now\s+)*'
    r'(?:approve|post|pay|delete|remove|create|make|send|email|cancel|reject|reverse|change|update|edit|confirm|verify|mark|'
    r'allocate|reconcile|import|write|add|set|record|enter|book|invoice|submit|release|unlock|reopen|transfer)\b')

# Question types, tried in this order. Each pattern runs on lower-case text without punctuation.
INTENT_PATTERNS = (
    ('help', r"\b(help|what can you (do|answer|tell)|what do you do|how (do|can) i use|how does this work|what can i ask|examples?)\b"),
    ('bank_balance', r"\b(bank balances?|balances? (at|in|with|of) (the |our )?banks?|money in (the )?bank|cash at (the )?bank|how much (money |cash )?(do we have |is there |have we got |is )?(in|at|with) (the |our )?banks?)\b"),
    ('work', r"\b(waiting for me|my (tasks?|work|to ?do|list|approvals?)|what (should|do|must|can|shall) i (do|need|work)|what needs (my attention|(my )?(action|doing))|to ?do (list )?(today)?|assigned to me|for me to (do|approve|verify|check)|pending (for|with|on) me|approvals? (waiting|pending|for me)|what is (on )?my plate)\b"),
    ('attention', r"\b(problems?|issues?|alerts?|what(?: is|'s|s) wrong|anything (wrong|urgent|odd|unusual)|needs attention|stuck|at risk|exceptions?)\b"),
    ('overdue', r"\b(overdue|past due|late (payments?|invoices?|customers?)|not paid on time|behind on pay(ing|ments?)|ageing|aging)\b"),
    ('owed_to_us', r"\b(who owes( us)?|owes us|owe us|owed to us|receivables?|outstanding (balances?|invoices?|payments?|receivables?)|unpaid (customer )?invoices?|money (we are|is) (owed|due)|collections?|customers? (owe|balance)|how much (do )?(they|customers?) owe)\b"),
    ('we_owe', r"\b(we owe|payables?|owe (to )?(our )?suppliers?|unpaid (supplier )?bills?|supplier (balance|bills? due)|bills? (to pay|due))\b"),
    ('lift', r"\b(left to lift|still to lift|remaining( mtl| quantity| material)?|to be lifted|not (yet )?lifted|pending lift(ing)?|how much (more )?(can|is left|to) (be )?lift(ed)?|lifting (left|remaining|pending)|mtl left|balance (to lift|quantity))\b"),
    ('bank_todo', r"\b(bank (lines?|payments?|statements?|receipts?)|unmatched|unidentified|who paid|payments? to (match|check)|to reconcile|duplicates?)\b"),
    ('kpis', r"\b(key figures|how are we doing|overview|summary|snapshot|numbers today|dashboard|how is (the )?business|where do we stand)\b"),
)
DOC_REF = re.compile(r'\b[A-Za-z]{1,6}(?:[-/][A-Za-z0-9]+)*[-/][A-Za-z0-9/\-.]*\d[A-Za-z0-9/\-.]*\b')
OLD_CODE = re.compile(r'(?<![\w/.-])(\d{1,3}(?:\.\d{1,3})+|\d{1,3})(?![\w/-])')
EXAMPLES = (   # (intent, question). Each is offered only to people who can have it answered.
    ('work', _lt("What is waiting for me?")), ('attention', _lt("Is anything wrong?")), ('kpis', _lt("Give me the key figures")),
    ('owed_to_us', _lt("Who owes us money?")), ('overdue', _lt("What is overdue?")), ('we_owe', _lt("What do we owe our suppliers?")),
    ('lift', _lt("How much is left to lift?")), ('bank_todo', _lt("How many bank payments need checking?")),
    ('bank_balance', _lt("What are the bank balances?")),
)


class _Denied(Exception):
    """A question that is understood but not allowed for this person. The message says why in plain words."""


def normalise(text):
    return re.sub(r'\s+', ' ', re.sub(r"[^\w\s.'/-]", ' ', (text or '').lower().replace('’', "'"))).strip()


def route(text):
    """Which type of question is this? Pure text work, no data is read: easy to test with many phrasings."""
    q = normalise(text)
    if not q:
        return None
    if COMMAND.match(q):
        return 'refuse'
    for key, pattern in INTENT_PATTERNS:
        if re.search(pattern, q):
            return key
    return None


class EiAssistant(models.AbstractModel):
    _name = 'ei.assistant'
    _description = 'Ask: read-only assistant'

    # ------------------------------------------------------------------ small helpers
    def _home(self):
        return self.env['ei.home']

    def _money(self, amount):
        return format_amount(self.env, amount or 0.0, self.env.company.currency_id)

    def _finance_ok(self):
        return self._home()._finance_ok()

    def _need_finance(self):
        if not self._finance_ok():
            raise _Denied(_("Money in the books is shown to finance and management only. Ask a finance colleague, or open Home to see what your role can see."))

    def _can_use(self, intent):
        env, home = self.env, self._home()
        if not env.user.has_group(USER_GROUP):
            return False
        if intent in ('owed_to_us', 'overdue', 'we_owe'):
            return bool(self._finance_ok() and env['ei.dashboard'].has_access('create'))
        if intent == 'bank_balance':
            return bool(env['ei.dashboard']._allowed('bank'))
        if intent == 'bank_todo':
            return env['ei.bank.import.line'].has_access('read')
        if intent == 'lift':
            return env['ei.da.line'].has_access('read')
        if intent == 'kpis':
            return bool(home._kpis(home._profile()[0], home._dash()))
        return True

    # ------------------------------------------------------------------ the answer envelope
    def _reply(self, intent, title, blocks, sources, how, kind='answer', suggestions=None, options=None):
        return {
            'kind': kind, 'intent': intent, 'title': title, 'blocks': blocks, 'sources': sources, 'how': how,
            'options': options or [], 'suggestions': suggestions or [],
            'as_of': fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime('%d %b %Y %H:%M'),
        }

    @staticmethod
    def _source(sources, label, kind, **params):
        item = dict(params, kind=kind, label=label)
        if item not in sources:
            sources.append(item)
        return sources.index(item)

    def _log(self, question, reply):
        outcome = {'answer': 'answered', 'choose': 'choose', 'unknown': 'unknown', 'denied': 'denied', 'refused': 'refused'}[reply['kind']]
        self.env['ei.assistant.log'].sudo().create({
            'user_id': self.env.user.id, 'question': (question or '')[:300], 'intent': reply['intent'] or False, 'outcome': outcome})

    # ------------------------------------------------------------------ public calls
    @api.model
    def starters(self):
        """Questions worth asking first: only ones this person can have answered."""
        return [str(q) for intent, q in EXAMPLES if self._can_use(intent)]

    @api.model
    def ask(self, question):
        question = (question or '').strip()
        reply = self._answer(question)
        self._log(question, reply)
        return reply

    @api.model
    def ask_party(self, partner_id):
        """The person picked one of several parties offered: summarise that exact party (no second guess)."""
        partner = self.env['res.partner'].browse(int(partner_id)).exists()
        if not partner:
            raise UserError(_("This party no longer exists."))
        partner.check_access('read')
        try:
            reply = self._party_answer(partner)
        except _Denied as e:
            reply = self._denied('party', str(e))
        self._log(_("Tell me about %s", partner.name), reply)
        return reply

    @api.model
    def open_source(self, source):
        """Where a source leads. Only the kinds below exist; each one is checked by the code that already guards that screen."""
        env, kind = self.env, (source or {}).get('kind')
        if kind == 'record':
            if source['model'] == 'account.move' and not self._finance_ok():      # the same rule as the search box: invoices are for finance roles
                raise AccessError(_("Your role cannot open invoices from here."))
            return env['ei.search'].open(source['model'], int(source['res_id']))
        if kind == 'task':
            return env['ei.work'].open_task(source['model'], int(source['res_id']))
        if kind == 'party':
            return env['ei.search'].open('ei.party360', int(source['partner_id']))
        if kind == 'party_metric':
            return env['ei.party360'].open_records(int(source['partner_id']), source['key'])
        if kind == 'kpi':
            return self._home().open_kpi(source['key'])
        if kind == 'alert':
            return self._home().open_alert(source['key'])
        if kind == 'action' and source.get('key') in ACTIONS:
            return env['ir.actions.actions']._for_xml_id(ACTIONS[source['key']])
        raise AccessError(_("This source cannot be opened."))

    # ------------------------------------------------------------------ the router
    def _denied(self, intent, text, kind='denied'):
        return self._reply(intent, _("I cannot do that for you"), [{'type': 'text', 'text': text}], [], _("Your role and the rules of the product decide what is shown."),
                           kind=kind, suggestions=self.starters()[:4])

    def _answer(self, question):
        env = self.env
        if not env.user.has_group(USER_GROUP):
            return self._denied(None, _("You do not have a role in this system yet. Ask your administrator to give you one."))
        q = normalise(question)
        if len(q) < 2:
            return self._unknown(question, _("Type a question, for example: %s", (self.starters() or [_("What is waiting for me?")])[0]))
        if ARABIC_SCRIPT.search(question):
            return self._unknown(question, _("I understand English questions for now. Urdu is planned but has not been reviewed by a native speaker yet, so I do not guess at it."))
        intent = route(question)
        try:
            if intent == 'refuse':
                return self._refuse()
            if intent:
                return getattr(self, '_h_' + intent)(question)
            return self._by_words(question)
        except _Denied as e:
            return self._denied(intent, str(e))

    def _refuse(self):
        return self._reply(
            'refuse', _("I can only look things up"),
            [{'type': 'text', 'text': _("I cannot approve, post, pay, send, change or delete anything. Those steps are done by a person with the right role, on the record itself, "
                                       "so that someone is accountable for them. I can show you what is waiting for you and open the record.")}],
            [], _("This assistant has no way to change a record: it only reads."), kind='refused', suggestions=self.starters()[:4])

    def _unknown(self, question, text, hits=None):
        blocks = [{'type': 'text', 'text': text}]
        sources = []
        if hits:
            blocks.append({'type': 'list', 'title': _("Records that match your words"), 'items': [
                {'text': h['title'], 'sub': h['subtitle'], 'src': self._source(sources, h['title'], 'record', model=h['model'], res_id=h['res_id'])} for h in hits]})
        return self._reply(None, _("I did not understand that as a question"), blocks, sources,
                           _("I match your words against the questions I know and against names and numbers in your records. Nothing matched well enough to answer."),
                           kind='unknown', suggestions=self.starters())

    # ------------------------------------------------------------------ entities: parties, document numbers, old codes
    def _words(self, question):
        return [w for w in normalise(question).split() if w not in STOP and len(w) > 1]

    def _parties(self, question):
        words = self._words(question)
        if not words:
            return []
        Search = self.env['ei.search']
        found, seen = [], set()
        for term in [' '.join(words)] + [w for w in words if len(w) >= 4 and len(words) > 1]:
            for r in Search.parties(term, limit=6, loose_limit=0):
                if r['partner_id'] and r['partner_id'] not in seen:
                    seen.add(r['partner_id'])
                    found.append(r)
            if found:
                break
        return found[:6]

    def _documents(self, question):
        """Records whose number appears in the question, matched exactly (never by similarity)."""
        out, Search = [], self.env['ei.search']
        for token in dict.fromkeys(DOC_REF.findall(question)):
            for g in Search.search(token)['groups']:
                for h in g['hits']:
                    pieces = [p.lower() for p in re.split(r'\s+', h['title'].replace('·', ' '))]
                    if h['model'] not in ('ei.party360', 'ei.legacy.code') and token.lower() in pieces and h not in out:
                        out.append(dict(h, group=g['label']))
        return out

    def _old_code(self, question):
        if 'ei.legacy.code' not in self.env or not self.env['ei.legacy.code'].has_access('read'):
            return None
        q = normalise(question)
        m = OLD_CODE.search(q)
        if not m or not (re.search(r'\bcodes?\b', q) or re.fullmatch(r'[\d.\s]+', q)):
            return None
        return m.group(1), self.env['ei.legacy.code'].search([('legacy_code', '=', m.group(1))])   # exact text: 1.3 never finds 1.03

    def _by_words(self, question):
        """No question type matched: a document number, an old code, a party name, or just words."""
        docs = self._documents(question)
        if len(docs) == 1:
            return self._document_answer(docs[0])
        if len(docs) > 1:
            return self._choose_records(question, docs)
        found = self._old_code(question)
        if found:
            text, codes = found
            if codes:
                return self._code_answer(codes)
            return self._unknown(question, _("There is no old code %s in the list. Codes are matched as exact text, so 1.3 is not 1.03.", text))
        parties = self._parties(question)
        if len(parties) == 1:
            return self._party_answer(self.env['res.partner'].browse(parties[0]['partner_id']))
        if len(parties) > 1:
            return self._choose_party(question, parties)
        words = ' '.join(self._words(question))
        hits = []
        if len(words) >= 2:
            for g in self.env['ei.search'].search(words)['groups']:
                hits += [dict(h, group=g['label']) for h in g['hits']]
        return self._unknown(question, _("I could not tell what you are asking, and nothing in your records is called that.") if not hits else
                             _("I could not tell what you are asking. These records contain your words; the first questions below always work."), hits[:6])

    def _choose_party(self, question, parties):
        return self._reply('party', _("Which one do you mean?"), [{'type': 'text', 'text': _("More than one party fits. Pick one and I will show you.")}], [],
                           _("These are the parties whose name, nickname, old code or approved bank name contains your words."), kind='choose',
                           options=[{'label': p['title'], 'sub': p['subtitle'], 'party_id': p['partner_id']} for p in parties])

    def _choose_records(self, question, docs):
        sources = []
        return self._reply('document', _("Which one do you mean?"), [{'type': 'text', 'text': _("More than one record has that number. Open the one you mean.")}], sources,
                           _("These records carry the number you typed, exactly."), kind='choose',
                           options=[{'label': d['title'], 'sub': '%s · %s' % (d['group'], d['subtitle']),
                                     'src': self._source(sources, d['title'], 'record', model=d['model'], res_id=d['res_id'])} for d in docs])

    # ------------------------------------------------------------------ answers: document, old code, party
    def _document_answer(self, hit):
        sources = []
        src = self._source(sources, hit['title'], 'record', model=hit['model'], res_id=hit['res_id'])
        return self._reply('document', hit['title'], [
            {'type': 'text', 'text': hit['group']}, {'type': 'text', 'text': hit['subtitle']},
            {'type': 'list', 'title': '', 'items': [{'text': _("Open %s", hit['title']), 'sub': _("The record itself, with its history"), 'src': src}]}],
            sources, _("Found by its number, exactly as you typed it, among the records your role can open."))

    def _code_answer(self, codes):
        sources, items = [], []
        for c in codes[:5]:
            status = dict(c._fields['verification_status']._description_selection(self.env)).get(c.verification_status, '')
            sub = ' · '.join(x for x in (c.nickname and _("nickname %s", c.nickname), c.source_sheet_key, status) if x)
            item = {'text': '%s  %s' % (c.legacy_code, c.original_name), 'sub': sub, 'src': self._source(sources, c.legacy_code, 'record', model='ei.legacy.code', res_id=c.id)}
            if c.linked_model == 'res.partner' and c.linked_res_id and self.env['res.partner'].browse(c.linked_res_id).exists():
                item['src2'] = self._source(sources, self.env['res.partner'].browse(c.linked_res_id).name, 'party', partner_id=c.linked_res_id)
                item['sub'] += ' · ' + _("linked to %s", self.env['res.partner'].browse(c.linked_res_id).name)
            items.append(item)
        return self._reply('code', _("Old code %s", codes[0].legacy_code), [{'type': 'list', 'title': '', 'items': items}], sources,
                           _("Looked up as exact text in the list of old codes (1.3 never finds 1.03). The old list is read-only; its status says whether a person has approved what it becomes."))

    def _party_answer(self, partner, only=None):
        env, p360 = self.env, self.env['ei.party360']
        data = p360.get_data(partner.id)
        sources = []
        sources_party = self._source(sources, _("%s: the whole page", partner.name), 'party', partner_id=partner.id)
        shown = [m for m in data['metrics'] if m['count']]
        items = [{'label': m['label'], 'value': m['text'], 'note': m['basis'], 'tone': m['tone'],
                  'src': self._source(sources, '%s - %s' % (partner.name, m['label']), 'party_metric', partner_id=partner.id, key=m['key'])} for m in shown][:8]
        quiet = [m['label'] for m in data['metrics'] if not m['count']]
        blocks = []
        codes = ', '.join(c['code'] for c in data['partner']['codes'][:4])
        if codes:
            blocks.append({'type': 'text', 'text': _("Old codes: %s", codes)})
        blocks.append({'type': 'figures', 'items': items} if items else {'type': 'text', 'text': _("Nothing is waiting or open for this party in the records your role can read.")})
        if quiet:
            blocks.append({'type': 'text', 'text': _("Nothing for: %s.", ', '.join(quiet[:6]))})
        if data['hidden']:
            blocks.append({'type': 'text', 'text': _("Not shown to your role: %s.", ', '.join(data['hidden']))})
        events = data['timeline'][:3]
        if events:
            openable = ('ei.contract', 'ei.da', 'ei.daily.order', 'ei.lifting', 'ei.supplier.intake', 'ei.bank.import.line', 'ei.cash.voucher', 'ei.parent.statement')
            blocks.append({'type': 'list', 'title': _("Latest"), 'items': [
                dict({'text': e['title'], 'sub': '%s · %s' % (e['date'], e['detail'])},
                     **({'src': self._source(sources, e['title'], 'record', model=e['model'], res_id=e['res_id'])} if e['model'] in openable else {})) for e in events]})
        blocks.append({'type': 'list', 'title': '', 'items': [{'text': _("Open the whole page for %s", partner.name), 'sub': _("Every figure explains itself and opens its records"), 'src': sources_party}]})
        return self._reply('party', partner.name, blocks, sources,
                           _("These are the figures of the Party 360 page, read as you. A figure only appears when there is something behind it, and it opens exactly the records it counts."))

    # ------------------------------------------------------------------ answers: what is waiting, problems, key figures
    def _h_help(self, question):
        lines = [{'text': q, 'sub': ''} for q in self.starters()]
        return self._reply('help', _("What I can do"), [
            {'type': 'text', 'text': _("I look things up in your own records and show where each answer comes from. I cannot change anything and I do not guess. You can also type a name, a document number such as a contract or delivery advice number, or an old code.")},
            {'type': 'list', 'title': _("Questions that work for your role"), 'items': lines}], [],
            _("The list is built from what your role is allowed to see."), suggestions=self.starters())

    def _h_work(self, question):
        work = self.env['ei.work'].tasks()
        mine = [t for t in work['items'] if t['can_act'] and not t['view_only']]
        sources = []
        if not mine:
            blocks = [{'type': 'text', 'text': _("Nothing is waiting for you right now.")}]
            others = work['counts'].get('others', 0)
            if others:
                blocks.append({'type': 'text', 'text': _("%s other item(s) you prepared yourself are waiting for a second person: you cannot approve your own work.", others)})
        else:
            rows = []
            for t in mine[:PER_TABLE]:
                src = None if t.get('bulk') else self._source(sources, t['title'], 'task', model=t['model'], res_id=t['res_id'])
                rows.append({'cells': [t['step'], t['title'], t['party'] or '', t['age_text']], 'src': src})
            blocks = [{'type': 'text', 'text': _("%s item(s) are waiting for you.", len(mine))},
                      {'type': 'table', 'columns': [_("Step"), _("Record"), _("Party"), _("Waiting")], 'rows': rows,
                       'more': (_("%s more are on Home.", len(mine) - PER_TABLE) if len(mine) > PER_TABLE else '')}]
        sources.append({'kind': 'action', 'key': 'home', 'label': _("My Work on Home")})
        return self._reply('work', _("What is waiting for you"), blocks, sources,
                           _("These are real records in a waiting state that your role can act on, oldest first. You are never asked to approve what you prepared yourself. It is the same list as My Work on Home."))

    def _h_attention(self, question):
        alerts = self._home()._alerts()
        sources = []
        if not alerts:
            return self._reply('attention', _("Nothing is flagged"), [{'type': 'text', 'text': _("None of the checks on Home raise anything: no duplicate bank payments, unidentified receipts, mismatched supplier invoices, rate differences, overdue approvals or parent-company differences in the records your role can read.")}],
                               [{'kind': 'action', 'key': 'home', 'label': _("Home")}], _("These are the same checks as the alerts on Home. A check that raises nothing means nothing was found by that check, not that nothing can be wrong."))
        items = [{'label': a['label'], 'value': str(a['count']), 'note': a['detail'], 'tone': a['severity'] if a['severity'] in ('danger', 'warning') else 'info',
                  'src': self._source(sources, a['label'], 'alert', key=a['key'])} for a in alerts]
        return self._reply('attention', _("What needs attention"), [{'type': 'figures', 'items': items}], sources,
                           _("Each one is a check on real records (duplicates, mismatches, differences, overdue approvals). They are the alerts on Home, and each opens the records it counted."))

    def _h_kpis(self, question):
        home = self._home()
        profile, _role = home._profile()
        kpis = home._kpis(profile, home._dash())
        if not kpis:
            raise _Denied(_("No figures are shown for your role."))
        sources = []
        items = [{'label': k['label'], 'value': k['value'], 'note': '%s · %s' % (k['sub'], k['basis']), 'tone': k['tone'],
                  'src': self._source(sources, k['label'], 'kpi', key=k['key'])} for k in kpis]
        return self._reply('kpis', _("Key figures"), [{'type': 'figures', 'items': items}], sources,
                           _("The figures on your Home page. Each says what it is based on (posted in the books, bank-confirmed, waiting for a person) and opens the records behind it."))

    # ------------------------------------------------------------------ answers: money (finance, management, auditor)
    def _ledger(self, kind, party=None):
        self._need_finance()
        if not self.env['ei.dashboard'].has_access('create'):
            raise _Denied(_("Your role cannot open the ledger figures."))
        dash = self.env['ei.dashboard'].create({})
        dom = dash._dom_lines(kind)
        if party:
            dom += [('partner_id', 'child_of', party.id)]
        return self.env['account.move.line'].sudo(), dom

    def _scope_party(self, question):
        parties = self._parties(question)
        if len(parties) == 1:
            return self.env['res.partner'].browse(parties[0]['partner_id'])
        return None

    def _by_party_table(self, L, dom, sign, sources, kind_metric):
        rows = L._read_group(dom, groupby=['partner_id'], aggregates=['amount_residual:sum', '__count'], order='amount_residual:sum desc' if sign > 0 else 'amount_residual:sum asc')
        total = sum(r[1] for r in rows) * sign
        table = []
        for partner, amount, n in rows[:PER_TABLE]:
            cells = [partner.name or _("(no party on the entry)"), self._money(amount * sign), str(n)]
            src = self._source(sources, partner.name, 'party_metric', partner_id=partner.id, key=kind_metric) if partner else None
            table.append({'cells': cells, 'src': src})
        return total, table, max(len(rows) - PER_TABLE, 0)

    def _h_owed_to_us(self, question):
        party = self._scope_party(question)
        L, dom = self._ledger('ar', party)
        sources = []
        today = fields.Date.context_today(self)
        if party:
            lines = L.search(dom)
            total = sum(lines.mapped('amount_residual'))
            late = sum(l.amount_residual for l in lines if (l.date_maturity or l.date) < today)
            sources.append({'kind': 'party_metric', 'partner_id': party.id, 'key': 'f_ar', 'label': _("%s: the open items", party.name)})
            sources.append({'kind': 'party', 'partner_id': party.id, 'label': _("%s: the whole page", party.name)})
            blocks = [{'type': 'figures', 'items': [{'label': _("%s owes us", party.name), 'value': self._money(total), 'note': _("Posted in the books"), 'tone': 'warning' if total else 'ok', 'src': 0},
                                                    {'label': _("Of which overdue"), 'value': self._money(late), 'note': _("Due date has passed"), 'tone': 'warning' if late else 'ok', 'src': 0}]}]
            how = _("Open receivable items in the posted ledger for this party, in company currency. Draft invoices and unmatched bank lines are not included. Same figure as 'They owe us' on Party 360.")
            return self._reply('owed_to_us', _("What %s owes us", party.name), blocks, sources, how)
        total, table, more = self._by_party_table(L, dom, 1, sources, 'f_ar')
        sources.append({'kind': 'kpi', 'key': 'ar', 'label': _("All open customer items")})
        blocks = [{'type': 'figures', 'items': [{'label': _("Customers owe us"), 'value': self._money(total), 'note': _("Posted in the books"), 'tone': 'warning' if total else 'ok', 'src': len(sources) - 1}]},
                  {'type': 'table', 'columns': [_("Customer"), _("Owes us"), _("Open items")], 'rows': table, 'more': (_("%s more customers are not shown.", more) if more else '')}]
        return self._reply('owed_to_us', _("Who owes us money"), blocks, sources,
                           _("Open receivable items in the posted ledger, added up per customer, largest first, in company currency. Draft invoices and unmatched bank lines are not included. The total is the 'Customers owe us' figure on Home."))

    def _h_we_owe(self, question):
        party = self._scope_party(question)
        L, dom = self._ledger('ap', party)
        sources = []
        if party:
            total = -sum(L.search(dom).mapped('amount_residual'))
            sources.append({'kind': 'party_metric', 'partner_id': party.id, 'key': 'f_ap', 'label': _("%s: the open items", party.name)})
            return self._reply('we_owe', _("What we owe %s", party.name),
                               [{'type': 'figures', 'items': [{'label': _("We owe %s", party.name), 'value': self._money(total), 'note': _("Posted in the books"), 'tone': 'warning' if total else 'ok', 'src': 0}]}],
                               sources, _("Open payable items in the posted ledger for this party, in company currency. Supplier invoices still being checked are not included. Same figure as 'We owe them' on Party 360."))
        total, table, more = self._by_party_table(L, dom, -1, sources, 'f_ap')
        sources.append({'kind': 'kpi', 'key': 'ap', 'label': _("All open supplier items")})
        blocks = [{'type': 'figures', 'items': [{'label': _("We owe suppliers"), 'value': self._money(total), 'note': _("Posted in the books"), 'tone': 'neutral', 'src': len(sources) - 1}]},
                  {'type': 'table', 'columns': [_("Supplier"), _("We owe"), _("Open items")], 'rows': table, 'more': (_("%s more suppliers are not shown.", more) if more else '')}]
        return self._reply('we_owe', _("What we owe our suppliers"), blocks, sources,
                           _("Open payable items in the posted ledger, added up per supplier, largest first, in company currency. Supplier invoices still being checked are not included. The total is 'We owe suppliers' on Home."))

    def _h_overdue(self, question):
        party = self._scope_party(question)
        L, dom = self._ledger('ar', party)
        today = fields.Date.context_today(self)
        lines = L.search(dom).filtered(lambda l: (l.date_maturity or l.date) < today)
        sources = []
        buckets = {'1-30': 0.0, '31-60': 0.0, '61-90': 0.0, 'over 90': 0.0}
        for l in lines:
            age = (today - (l.date_maturity or l.date)).days
            buckets['1-30' if age <= 30 else '31-60' if age <= 60 else '61-90' if age <= 90 else 'over 90'] += l.amount_residual
        total = sum(lines.mapped('amount_residual'))
        who = _(" for %s", party.name) if party else ''
        if not lines:
            return self._reply('overdue', _("Nothing is overdue%s", who), [{'type': 'text', 'text': _("No open customer item has passed its due date.")}],
                               [{'kind': 'kpi', 'key': 'ar', 'label': _("All open customer items")}], _("Open receivable items in the posted ledger whose due date has passed."))
        oldest = sorted(lines, key=lambda l: l.date_maturity or l.date)[:PER_TABLE]
        rows = []
        for l in oldest:
            due = l.date_maturity or l.date
            src = self._source(sources, l.move_id.name, 'record', model='account.move', res_id=l.move_id.id)
            rows.append({'cells': [l.move_id.name, l.partner_id.name or '', self._money(l.amount_residual), format_date(self.env, due, date_format='dd MMM yyyy'), str((today - due).days)], 'src': src})
        sources.append({'kind': 'kpi', 'key': 'ar', 'label': _("All open customer items")})
        figs = [{'label': _("Overdue in total"), 'value': self._money(total), 'note': _("%s open item(s)", len(lines)), 'tone': 'warning', 'src': len(sources) - 1}]
        figs += [{'label': _("%s days late", k), 'value': self._money(v), 'note': '', 'tone': 'neutral'} for k, v in buckets.items() if v]
        return self._reply('overdue', _("What is overdue%s", who), [
            {'type': 'figures', 'items': figs},
            {'type': 'table', 'columns': [_("Invoice"), _("Customer"), _("Open amount"), _("Due"), _("Days late")], 'rows': rows,
             'more': (_("%s more overdue items are not shown.", len(lines) - PER_TABLE) if len(lines) > PER_TABLE else '')}], sources,
            _("Open receivable items in the posted ledger whose due date is before today, oldest first. The total equals 'Customers owe us' minus 'Not yet due' on the management dashboard."))

    # ------------------------------------------------------------------ answers: material, bank
    def _h_lift(self, question):
        if not self._can_use('lift'):
            raise _Denied(_("Delivery quantities are shown to people who work with delivery advices."))
        env, sources = self.env, []
        docs = [d for d in self._documents(question) if d['model'] == 'ei.da']
        if len(docs) == 1:
            da = env['ei.da'].browse(docs[0]['res_id'])
            rows = [{'cells': [l.customer_id.name or da.parent_partner_id.name or '', '{:,.3f}'.format(l.mtl), '{:,.3f}'.format(l.lifted_mtl), '{:,.3f}'.format(l.remaining_to_lift)]} for l in da.line_ids]
            src = self._source(sources, da.name, 'record', model='ei.da', res_id=da.id)
            return self._reply('lift', _("Still to lift on %s", da.name), [
                {'type': 'figures', 'items': [{'label': _("Still to lift"), 'value': '{:,.3f} MTL'.format(da.remaining_to_lift), 'note': _("Approved minus verified"), 'tone': 'warning' if da.remaining_to_lift > 0.0005 else 'ok', 'src': src}]},
                {'type': 'table', 'columns': [_("Customer"), _("Approved MTL"), _("Verified lifted MTL"), _("Still to lift")], 'rows': rows, 'more': ''}], sources,
                _("Approved MTL on each line of the delivery advice minus the MTL of truck loadings that a second person verified against the gate pass and weighbridge slip. A supplier invoice never counts as lifting."))
        party = self._scope_party(question)
        if party:
            data = env['ei.party360'].get_data(party.id)
            keep = [m for m in data['metrics'] if m['key'] in ('m_approved', 'm_ordered', 'm_lifted', 'm_remaining', 'l_to_invoice')]
            items = [{'label': m['label'], 'value': m['text'], 'note': m['basis'], 'tone': m['tone'],
                      'src': self._source(sources, '%s - %s' % (party.name, m['label']), 'party_metric', partner_id=party.id, key=m['key'])} for m in keep]
            return self._reply('lift', _("Still to lift for %s", party.name), [{'type': 'figures', 'items': items}] if items else [{'type': 'text', 'text': _("Your role does not see delivery quantities for this party.")}],
                               sources, _("The material figures of the Party 360 page: approved on delivery advices, asked for on daily orders, truly lifted (verified) and still to lift (approved minus verified, line by line)."))
        lines = env['ei.da.line'].search([('state', '=', 'approved')])
        total = sum(lines.mapped('remaining_to_lift'))
        over = lines.filtered(lambda l: l.remaining_to_lift < -0.0005)
        per_da = {}
        for l in lines.filtered(lambda l: l.remaining_to_lift > 0.0005):
            per_da[l.da_id] = per_da.get(l.da_id, 0.0) + l.remaining_to_lift
        rows = []
        for da, rem in sorted(per_da.items(), key=lambda kv: -kv[1])[:PER_TABLE]:
            src = self._source(sources, da.name, 'record', model='ei.da', res_id=da.id)
            rows.append({'cells': [da.name, da.parent_partner_id.name or '', '{:,.3f}'.format(da.total_mtl), '{:,.3f}'.format(rem)], 'src': src})
        blocks = [{'type': 'figures', 'items': [{'label': _("Still to lift in total"), 'value': '{:,.3f} MTL'.format(total), 'note': _("Approved minus verified"), 'tone': 'warning' if total > 0.0005 else 'ok'}]},
                  {'type': 'table', 'columns': [_("Delivery advice"), _("Parent company"), _("Approved MTL"), _("Still to lift")], 'rows': rows,
                   'more': (_("%s more delivery advices are not shown.", len(per_da) - PER_TABLE) if len(per_da) > PER_TABLE else '')}]
        if over:
            blocks.append({'type': 'text', 'text': _("%(n)s line(s) were lifted beyond what was approved (%(q)s MTL). They are included in the total, as on Party 360.", n=len(over), q='{:,.3f}'.format(sum(over.mapped('remaining_to_lift'))))})
        return self._reply('lift', _("How much is left to lift"), blocks, sources,
                           _("For each approved delivery advice line: approved MTL minus the MTL of verified truck loadings, added up. Lines are listed by delivery advice, largest remainder first."))

    def _h_bank_todo(self, question):
        if not self._can_use('bank_todo'):
            raise _Denied(_("Bank payments are shown to bank officers, approvers, finance and management."))
        q = self.env['ei.matching'].queue('check')
        sources = []
        counts = {t['key']: t for t in q['tabs']}
        tone = {'check': 'warning', 'allocate': 'warning', 'unidentified': 'danger', 'duplicates': 'danger'}
        items = [{'label': counts[k]['label'], 'value': str(counts[k]['count']), 'note': '', 'tone': tone[k] if counts[k]['count'] else 'ok'} for k in ('check', 'allocate', 'unidentified', 'duplicates')]
        if q['deferred']:
            items.append({'label': _("Put aside by you"), 'value': str(q['deferred']), 'note': '', 'tone': 'neutral'})
        sources.append({'kind': 'action', 'key': 'matching', 'label': _("Match bank payments")})
        for key, label in (('unidentified', _("Bank receipts nobody has identified")), ('dup_payment', _("Possible duplicate bank payments"))):
            if self._home()._count('ei.bank.import.line', [('state', '=', 'unidentified' if key == 'unidentified' else 'duplicate')]):
                sources.append({'kind': 'alert', 'key': key, 'label': label})
        return self._reply('bank_todo', _("Bank payments that need a person"), [{'type': 'figures', 'items': items}], sources,
                           _("Counts of staged bank lines in statements that are not yet approved, by what is left to do. They are the lists on the Match bank payments screen. Suggested payers are not counted as confirmed."))

    def _h_bank_balance(self, question):
        banks = self._home()._banks()
        if not banks:
            raise _Denied(_("Bank balances are shown to bank officers, approvers, finance and management."))
        sources = [{'kind': 'kpi', 'key': 'bank', 'label': _("Bank balances")}]
        rows = [{'cells': [b['name'], b['balance'], b['text']], 'src': 0} for b in banks]
        return self._reply('bank_balance', _("Bank balances"), [{'type': 'table', 'columns': [_("Bank account"), _("Balance in the books"), _("Confirmed with the bank")], 'rows': rows, 'more': ''}],
                           sources, _("The balance is what the books say for each bank account today. The last column says whether someone confirmed it with the bank (a phone call, SMS or portal) and whether it matched."))
