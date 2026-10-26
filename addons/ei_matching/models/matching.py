"""Payment matching: every bank line that still needs a person, decided on one screen.

This model is only a *front* for rules that already exist. It never decides anything and never touches the books:
  * "who paid" is confirmed by ei.bank.import.line.action_verify_partner (evidence note rule included),
  * "which invoices" is saved as ei.bank.allocation rows, which check the party, the direction, the open amount and the
    total themselves,
  * a line only reaches the ledger when its statement is approved by a bank approver and posted by a different person
    (ei.bank.import.action_approve / action_post). Nothing here approves or posts.
A suggestion (an alias, an equal amount, an "oldest invoices first" proposal) is only ever shown and labelled as a
suggestion. It becomes a fact only when an officer confirms it, and the confirmation is recorded on the line.
Every call runs as the current user, so access rules and the bank groups decide what can be seen and done.
"""
import itertools
import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext
from odoo.tools.misc import format_amount, format_date, format_datetime
from odoo.tools.translate import LazyTranslate

from odoo.addons.ei_bank_operations.models import bank_parsing as bp
from odoo.addons.ei_bank_operations.models.bank_import import LOCKED_STATES
from odoo.addons.ei_ui_theme.models.search import _like

_lt = LazyTranslate(__name__)

OFFICER = 'ei_bank_operations.group_ei_bank_officer'
APPROVER = 'ei_bank_operations.group_ei_bank_approver'
MODEL = 'ei.bank.import.line'
STRONG = 0.9               # the same bar action_verify_partner uses: below it an evidence note is always required
TWIN_DAYS = 7              # another bank line of the same amount this close in time is shown as a warning
PAGE = 60
MAX_OPEN_ITEMS = 40
SUBSET_POOL = 14           # the exact-sum proposal looks at the 14 longest-open items, at most 3 at a time
DEFER_CHOICES = (1, 3, 7)

TABS = (
    ('check', _lt("To check")),
    ('allocate', _lt("Waiting for allocation")),
    ('unidentified', _lt("Unidentified")),
    ('duplicates', _lt("Duplicates")),
)
TAB_STATES = {'check': ('new', 'proposed'), 'allocate': ('verified',), 'unidentified': ('unidentified',), 'duplicates': ('duplicate',)}
KIND_WORD = {
    'out_invoice': _lt("Customer invoice"), 'in_invoice': _lt("Supplier bill"),
    'out_refund': _lt("Customer credit note"), 'in_refund': _lt("Supplier credit note"),
}
SUGGESTION_WORD = {
    'approved_alias': _lt("Matches a name that was approved for this party. Strong, but still check it."),
    'proposed_alias': _lt("Matches a name nobody has approved yet. Treat it as a guess."),
    'amount': _lt("The amount equals one open invoice of this party. That is a guess, not evidence."),
}


class EiMatching(models.AbstractModel):
    _name = 'ei.matching'
    _description = 'Payment matching workbench'

    # ------------------------------------------------------------------ small helpers
    def _officer(self):
        return self.env.user.has_group(OFFICER)

    def _need_officer(self):
        if not self._officer():
            raise AccessError(_("Only bank officers can decide on bank lines."))

    def _line(self, line_id):
        line = self.env[MODEL].browse(int(line_id)).exists()
        if not line:
            raise UserError(_("This bank line no longer exists."))
        line.check_access('read')
        return line

    def _need_open(self, line):
        if line.import_id.state in LOCKED_STATES:
            raise UserError(_("Statement %(b)s is %(s)s, so its lines can no longer be changed.",
                              b=line.import_id.name, s=dict(line.import_id._fields['state']._description_selection(self.env))[line.import_id.state]))

    def _label(self, rec, field):
        return dict(rec._fields[field]._description_selection(self.env)).get(rec[field], rec[field])

    def _money(self, amount, line):
        return format_amount(self.env, abs(amount), line.currency_id)

    @staticmethod
    def _kind(line):
        """How strong the suggestion on a line is. The numbers are the ones ei.bank.import.line._suggest_partner writes."""
        if not line.suggested_partner_id:
            return 'none'
        if line.confidence >= STRONG:
            return 'approved_alias'
        return 'amount' if abs(line.confidence - 0.5) < 0.01 else 'proposed_alias'

    def _snoozed(self):
        Snooze = self.env['ei.work.snooze']
        if not Snooze.has_access('read'):
            return set()
        return set(Snooze.search([('user_id', '=', self.env.user.id), ('res_model', '=', MODEL),
                                  ('until', '>', fields.Date.context_today(self))]).mapped('res_id'))

    def _remaining(self, line):
        return line.currency_id.round(abs(line.amount) - line.allocated)

    # ------------------------------------------------------------------ the queue
    def _search_domain(self, q):
        q = (q or '').strip()
        if not q:
            return []
        t = _like(q)
        dom = ['|', '|', '|', ('narration', 'ilike', t), ('ref', 'ilike', t), ('partner_id.name', 'ilike', t),
               ('suggested_partner_id.name', 'ilike', t)]
        try:
            amount = float(re.sub(r'[,\s]', '', q))
        except ValueError:
            return dom
        return ['|', ('amount', 'in', [amount, -amount])] + dom

    def _tab_lines(self, tab, domain, limit=None):
        """The lines of one list, oldest first. 'Waiting for allocation' also needs the amount still unallocated, which the
        database cannot filter on, so that list is filtered here (it only holds confirmed, unfinished lines)."""
        lines = self.env[MODEL].search(domain + [('state', 'in', TAB_STATES[tab])], order='date asc, id asc', limit=None if tab == 'allocate' else limit)
        if tab == 'allocate':
            lines = lines.filtered(lambda l: not l.currency_id.is_zero(self._remaining(l)))
        return lines

    def _tab_count(self, tab, base, snoozed):
        """(lines on my list, lines I put aside) for one tab."""
        Line = self.env[MODEL]
        if tab == 'allocate':
            lines = self._tab_lines(tab, base)
            aside = len(lines.filtered(lambda l: l.id in snoozed))
            return len(lines) - aside, aside
        dom = base + [('state', 'in', TAB_STATES[tab])]
        aside = Line.search_count(dom + [('id', 'in', list(snoozed))]) if snoozed else 0
        return Line.search_count(dom) - aside, aside

    @api.model
    def queue(self, tab='check', q='', journal_id=False, deferred=False):
        Line = self.env[MODEL]
        if not Line.has_access('read'):
            return {'tabs': [], 'items': [], 'total': 0, 'deferred': 0, 'journals': [], 'can_review': False, 'tab': tab}
        tab = tab if tab in TAB_STATES else 'check'
        open_batches = [('import_id.state', 'not in', LOCKED_STATES)]
        base = open_batches + ([('journal_id', '=', int(journal_id))] if journal_id else [])
        snoozed = self._snoozed()
        counts, put_aside = {}, 0
        for key, _name in TABS:
            counts[key], aside = self._tab_count(key, base, snoozed)
            put_aside += aside
        mine = [('id', 'in', list(snoozed))] if deferred else ([('id', 'not in', list(snoozed))] if snoozed else [])
        domain = base + self._search_domain(q) + mine
        lines = self._tab_lines(tab, domain, limit=PAGE)
        total = len(lines) if tab == 'allocate' else Line.search_count(domain + [('state', 'in', TAB_STATES[tab])])
        lines = lines[:PAGE]
        twins = self._twin_map(lines)
        journals = self.env['account.journal'].browse([j.id for (j,) in Line._read_group(open_batches, groupby=['journal_id'])])
        return {
            'tabs': [{'key': k, 'label': str(label), 'count': counts[k]} for k, label in TABS],
            'items': [self._item(l, twins.get(l.id), snoozed) for l in lines],
            'total': total, 'deferred': put_aside, 'tab': tab,
            'journals': [{'id': j.id, 'name': j.name} for j in journals.sorted('name')],
            'can_review': self._officer(),
        }

    def _item(self, line, twins=None, snoozed=()):
        today = fields.Date.context_today(self)
        inbound = line.amount > 0
        return {
            'id': line.id, 'date': fields.Date.to_string(line.date), 'date_text': format_date(self.env, line.date, date_format='dd MMM'),
            'age_days': max((today - line.date).days, 0) if line.date else 0, 'inbound': inbound,
            'direction': _("Received") if inbound else _("Paid out"),
            'amount_text': self._money(line.amount, line), 'narration': line.narration or '', 'ref': line.ref or '',
            'journal': line.journal_id.name, 'batch': line.import_id.name, 'state': line.state, 'state_label': self._label(line, 'state'),
            'party': line.partner_id.name or '', 'suggested': line.suggested_partner_id.name or '',
            'suggested_pct': round(line.confidence * 100) if line.suggested_partner_id else 0,
            'kind': self._kind(line), 'remaining_text': self._money(self._remaining(line), line), 'twin': bool(twins),
            'deferred': line.id in snoozed,
        }

    def _twin_map(self, lines):
        """Other bank lines with the same amount close in time: two deposits of 50,000 on one day may be two customers or
        one payment seen twice. The screen shows the warning; only a person can tell."""
        if not lines:
            return {}
        others = self.env[MODEL].search([('company_id', 'in', lines.company_id.ids), ('state', '!=', 'rejected'),
                                         ('amount', 'in', list(set(lines.mapped('amount'))))])
        out = {}
        for l in lines:
            out[l.id] = others.filtered(lambda o: o.id != l.id and o.currency_id == l.currency_id and l.date and o.date
                                        and l.currency_id.is_zero(o.amount - l.amount) and abs((o.date - l.date).days) <= TWIN_DAYS)
        return out

    # ------------------------------------------------------------------ the decision
    @api.model
    def search_party(self, term):
        term = (term or '').strip()
        if len(term) < 2:
            return []
        return [{'partner_id': r['partner_id'], 'name': r['title'], 'sub': r['subtitle']}
                for r in self.env['ei.search'].parties(term, limit=8) if r['partner_id']]

    def _alias_options(self, line):
        """Parties whose known names appear in the narration, so an ambiguous line can be settled with one click."""
        narr = bp.normalise_text(line.narration)
        hits = self.env['ei.partner.alias'].search([('company_id', '=', line.company_id.id)]).filtered(lambda a: a.alias_norm in narr)
        out = {}
        for a in hits:
            row = out.setdefault(a.partner_id.id, {'partner_id': a.partner_id.id, 'name': a.partner_id.name, 'approved': False, 'alias': a.alias})
            row['approved'] = row['approved'] or a.state == 'approved'
        return sorted(out.values(), key=lambda r: (not r['approved'], r['name']))

    def _open_items(self, line, partner):
        """Open invoices / bills of this party that this bank line could settle, in the line's own currency."""
        inbound = line.amount > 0
        types = ('out_invoice', 'in_refund') if inbound else ('in_invoice', 'out_refund')
        base = [('company_id', '=', line.company_id.id), ('state', '=', 'posted'), ('move_type', 'in', types),
                ('commercial_partner_id', '=', partner.commercial_partner_id.id), ('amount_residual', '>', 0)]
        Move = self.env['account.move']
        moves = Move.search(base + [('currency_id', '=', line.currency_id.id)], order='invoice_date_due asc, id asc', limit=MAX_OPEN_ITEMS)
        moves |= line.allocation_ids.invoice_id
        return moves, Move.search_count(base + [('currency_id', '!=', line.currency_id.id)])

    def _pending_elsewhere(self, line, moves):
        """Money other staged bank lines already claim on these invoices (not in the books yet, so the invoice still shows it open)."""
        rows = self.env['ei.bank.allocation'].search([('invoice_id', 'in', moves.ids), ('line_id', '!=', line.id), ('line_id.state', '=', 'verified')])
        out = {}
        for a in rows:
            out.setdefault(a.invoice_id.id, []).append(a)
        return out

    def _candidate(self, line, move, pending, mine):
        today = fields.Date.context_today(self)
        claimed = sum(a.amount for a in pending.get(move.id, []))
        available = max(line.currency_id.round(move.amount_residual - claimed), 0.0)
        due = move.invoice_date_due
        return {
            'invoice_id': move.id, 'name': move.name, 'kind': str(KIND_WORD.get(move.move_type, move.move_type)),
            'date_text': format_date(self.env, move.invoice_date, date_format='dd MMM yyyy') if move.invoice_date else '',
            'due_text': format_date(self.env, due, date_format='dd MMM yyyy') if due else '',
            'overdue_days': max((today - due).days, 0) if due else 0,
            'total_text': self._money(move.amount_total, line), 'residual': move.amount_residual, 'residual_text': self._money(move.amount_residual, line),
            'claimed': claimed, 'claimed_text': self._money(claimed, line), 'claimed_by': sorted({a.line_id.narration or a.line_id.display_name for a in pending.get(move.id, [])})[:2],
            'available': available, 'available_text': self._money(available, line),
            'exact': line.currency_id.is_zero(abs(line.amount) - move.amount_residual), 'mine': mine.get(move.id, 0.0),
        }

    def _impact(self, line, allocations):
        """What posting this line WILL do, worked out from the saved allocations. A preview: nothing is posted from this screen."""
        inbound = line.amount > 0
        journal, cur = line.journal_id, line.currency_id
        rows = [{'kind': 'bank', 'account': journal.default_account_id.display_name or journal.name,
                 'side': _("Debit") if inbound else _("Credit"), 'amount_text': self._money(line.amount, line),
                 'plain': _("%(j)s goes up", j=journal.name) if inbound else _("%(j)s goes down", j=journal.name)}]
        for a in allocations:
            inv = a.invoice_id
            side = inv.line_ids.filtered(lambda l: l.account_type in ('asset_receivable', 'liability_payable'))[:1]
            after = cur.round(inv.amount_residual - a.amount)
            rows.append({'kind': 'party', 'account': side.account_id.display_name or '', 'side': _("Credit") if inbound else _("Debit"),
                         'amount_text': self._money(a.amount, line), 'invoice': inv.name,
                         'plain': _("%(i)s: open amount goes from %(a)s to %(b)s", i=inv.name, a=self._money(inv.amount_residual, line), b=self._money(after, line)),
                         'settled': cur.is_zero(after)})
        left = self._remaining(line)
        if left > 0:
            rows.append({'kind': 'suspense', 'account': journal.suspense_account_id.display_name or '',
                         'side': _("Credit") if inbound else _("Debit"), 'amount_text': self._money(left, line),
                         'plain': _("%s stays unallocated on the bank suspense account until someone allocates it. Nothing is guessed.", self._money(left, line))})
        return rows

    def _history(self, line):
        out = []
        for m in self.env['mail.message'].sudo().search([('model', '=', MODEL), ('res_id', '=', line.id), ('message_type', 'in', ('comment', 'notification'))],
                                                          order='id desc', limit=8):
            text = html2plaintext(m.body or '').strip()
            if text:
                out.append({'who': m.author_id.name or _("System"), 'when': format_datetime(self.env, m.date, dt_format='dd MMM HH:mm'), 'text': text[:240]})
        return out

    def _recent_with(self, line, partner):
        """The last payments already in the books for this party: what their bank narrations usually look like."""
        past = self.env[MODEL].search([('partner_id', '=', partner.id), ('state', '=', 'posted'), ('id', '!=', line.id)], order='date desc, id desc', limit=3)
        return [{'date_text': format_date(self.env, p.date, date_format='dd MMM yyyy'), 'amount_text': self._money(p.amount, p), 'narration': p.narration or ''} for p in past]

    def _people(self, line):
        users = (self.env.ref(OFFICER).sudo().user_ids | self.env.ref(APPROVER).sudo().user_ids).filtered(
            lambda u: u.active and not u.share and u != self.env.user and line.with_user(u).has_access('read'))
        return [{'id': u.id, 'name': u.name} for u in users.sorted('name')[:15]]

    @api.model
    def detail(self, line_id):
        line = self._line(line_id)
        env, cur = self.env, line.currency_id
        locked = line.import_id.state in LOCKED_STATES
        officer = self._officer()
        editable = officer and not locked and line.state not in ('duplicate', 'rejected', 'posted')
        inbound = line.amount > 0
        snoozed = self._snoozed()
        twins = self._twin_map(line)[line.id]
        confirmed = line.partner_id if line.state == 'verified' else env['res.partner']
        shown = confirmed or line.suggested_partner_id
        sug = None
        if line.suggested_partner_id or line.match_note:
            kind = self._kind(line)
            sug = {'partner_id': line.suggested_partner_id.id or False, 'name': line.suggested_partner_id.name or '', 'pct': round(line.confidence * 100),
                   'kind': kind, 'why': str(SUGGESTION_WORD.get(kind, '')), 'note': line.match_note or '', 'needs_note': kind != 'approved_alias'}
        moves, foreign = (self._open_items(line, shown) if shown and line.state in ('new', 'proposed', 'verified') else (env['account.move'], 0))
        pending = self._pending_elsewhere(line, moves) if moves else {}
        mine = {a.invoice_id.id: a.amount for a in line.allocation_ids}
        batch = line.import_id
        dup = line.duplicate_of_id
        return {
            'line': self._item(line, twins, snoozed),
            'batch': {'id': batch.id, 'name': batch.name, 'state': batch.state, 'state_label': self._label(batch, 'state'),
                      'filename': batch.filename or '', 'imported_by': batch.imported_by.name or '',
                      'imported_at': format_datetime(env, batch.imported_at, dt_format='dd MMM yyyy HH:mm') if batch.imported_at else ''},
            'question': _("Who paid this?") if inbound else _("Who was paid?"),
            'locked': locked, 'locked_text': _("This statement is already %s, so its lines are locked.", self._label(batch, 'state')) if locked else '',
            'evidence': [x for x in (
                (_("Bank narration"), line.narration or ''), (_("Bank reference"), line.ref or ''),
                (_("Bank balance after this line"), self._money(line.balance, line) if line.has_balance else ''),
                (_("Statement file"), batch.filename or ''), (_("Fingerprint"), (line.fingerprint or '')[:12])) if x[1]],
            'suggestion': sug, 'options': self._alias_options(line) if line.state in ('new', 'proposed', 'unidentified') else [],
            'party': {'partner_id': confirmed.id, 'name': confirmed.name, 'by': line.verified_by.name or '', 'note': line.evidence_note or ''} if confirmed else None,
            'unidentified_note': line.evidence_note or '' if line.state == 'unidentified' else '',
            'recent': self._recent_with(line, shown) if shown else [],
            'twins': [{'id': t.id, 'date_text': format_date(env, t.date, date_format='dd MMM yyyy'), 'amount_text': self._money(t.amount, t),
                       'narration': t.narration or '', 'state_label': self._label(t, 'state'), 'same_statement': t.import_id == batch} for t in twins],
            'duplicate_of': {'id': dup.id, 'date_text': format_date(env, dup.date, date_format='dd MMM yyyy'), 'amount_text': self._money(dup.amount, dup),
                             'narration': dup.narration or '', 'state_label': self._label(dup, 'state'), 'statement': dup.import_id.name} if dup else None,
            'preview_party': bool(shown) and not confirmed,
            'open_items': [self._candidate(line, m, pending, mine) for m in moves],
            'foreign_items': foreign,
            'allocations': [{'invoice_id': a.invoice_id.id, 'name': a.invoice_id.name, 'amount': a.amount} for a in line.allocation_ids],
            'allocated': line.allocated, 'allocated_text': self._money(line.allocated, line),
            'remaining': self._remaining(line), 'remaining_text': self._money(self._remaining(line), line), 'total': abs(line.amount),
            'impact': self._impact(line, line.allocation_ids),
            'after': [str(_("A bank approver checks the whole statement %(b)s. It cannot be %(who)s.", b=batch.name, who=batch.imported_by.name or _("the person who imported it"))),
                      str(_("A different person posts it into the books. Until then nothing here changes the ledger."))],
            'history': self._history(line), 'people': self._people(line) if officer else [],
            'can': {'confirm': editable, 'allocate': editable and line.state == 'verified', 'unidentified': editable, 'reject': officer and not locked and line.state != 'posted',
                    'ask': officer, 'defer': officer and self.env['ei.work.snooze'].has_access('create'), 'deferred': line.id in snoozed},
        }

    # ------------------------------------------------------------------ proposals (they never write anything)
    @api.model
    def suggest_allocation(self, line_id):
        """Which invoices this payment probably settles. A proposal for the officer to accept or change, never saved by itself."""
        line = self._line(line_id)
        if line.state != 'verified':
            raise UserError(_("Confirm who paid first; invoices are only proposed for a confirmed party."))
        moves, _foreign = self._open_items(line, line.partner_id)
        pending = self._pending_elsewhere(line, moves)
        cur, need = line.currency_id, abs(line.amount)
        items = [(m, self._candidate(line, m, pending, {})['available']) for m in moves if m not in line.allocation_ids.invoice_id]
        items = [(m, a) for m, a in items if a > 0]
        pool = items[:SUBSET_POOL]
        exact = []
        for size in (1, 2, 3):
            exact = [c for c in itertools.combinations(pool, size) if cur.is_zero(sum(a for _m, a in c) - need)]
            if exact:
                break
        if len(exact) == 1:
            why = _("These add up exactly to the payment.") if len(exact[0]) > 1 else _("This invoice has exactly the amount of the payment.")
            return {'items': [{'invoice_id': m.id, 'amount': a} for m, a in exact[0]], 'why': why,
                    'sure': True}
        left, out = need, []
        for m, a in items:                                    # oldest due first, never more than the open amount
            if left <= 0:
                break
            take = min(a, left)
            out.append({'invoice_id': m.id, 'amount': cur.round(take)})
            left = cur.round(left - take)
        why = (_("Several combinations add up exactly, so please choose. Until you do, this is the oldest invoices first.") if len(exact) > 1
               else _("No invoice or small group matches the payment exactly. This is the oldest invoices first; change it if the payer said otherwise."))
        return {'items': out, 'why': why, 'sure': False}

    # ------------------------------------------------------------------ decisions (each one is a real, audited step)
    def _done(self, line, text):
        return {'message': text, 'detail': self.detail(line.id)}

    @api.model
    def confirm_party(self, line_id, partner_id, note=None, clear_allocations=False):
        line = self._line(line_id)
        partner = self.env['res.partner'].browse(int(partner_id)).exists()
        if not partner:
            raise UserError(_("Choose the party."))
        mismatched = line.allocation_ids.filtered(lambda a: a.invoice_id.commercial_partner_id != partner.commercial_partner_id)
        if mismatched:
            if not clear_allocations:
                raise UserError(_("Some invoices are already allocated to %s. Changing the party removes those allocations.", line.partner_id.name))
            self._need_officer()
            self._need_open(line)
            mismatched.unlink()
        line.action_verify_partner(partner, note)
        line.message_post(body=_("Party confirmed as %(p)s by %(u)s.", p=partner.name, u=self.env.user.name))
        return self._done(line, _("Confirmed: %s", partner.name))

    @api.model
    def set_allocations(self, line_id, items):
        line = self._line(line_id)
        self._need_officer()
        self._need_open(line)
        if line.state != 'verified':
            raise UserError(_("Confirm who paid first. Invoices are allocated only to a confirmed party."))
        wanted = {}
        for it in items or []:
            amount = float(it.get('amount') or 0)
            if amount > 0:
                wanted[int(it['invoice_id'])] = wanted.get(int(it['invoice_id']), 0.0) + amount
        cur = line.currency_id
        Alloc = self.env['ei.bank.allocation'].with_context(ei_no_alloc_log=True)     # one summary below instead of a note per row
        with self.env.cr.savepoint():
            line.allocation_ids.with_context(ei_no_alloc_log=True).unlink()
            allocs = Alloc.create([{'line_id': line.id, 'invoice_id': i, 'amount': cur.round(a)} for i, a in wanted.items()])
        if allocs:
            what = '; '.join('%s %s' % (self._money(a.amount, line), a.invoice_id.name) for a in allocs)
            line.message_post(body=_("Allocation saved by %(u)s: %(w)s.", u=self.env.user.name, w=what))
        else:
            line.message_post(body=_("Allocation cleared by %s.", self.env.user.name))
        return self._done(line, _("Allocation saved. %s is still unallocated.", self._money(self._remaining(line), line)) if self._remaining(line) > 0
                          else _("Allocation saved. The whole payment is allocated."))

    @api.model
    def mark_unidentified(self, line_id, note=None, clear_allocations=False):
        line = self._line(line_id)
        if line.allocation_ids and clear_allocations:
            self._need_officer()
            self._need_open(line)
            line.allocation_ids.unlink()
        line.action_mark_unidentified(note)
        line.message_post(body=_("Marked unidentified by %s.", self.env.user.name))
        return self._done(line, _("Marked unidentified. It stays on the list until someone finds the payer."))

    @api.model
    def reject(self, line_id, reason):
        line = self._line(line_id)
        line.action_reject(reason)
        line.message_post(body=_("Rejected by %(u)s: %(r)s", u=self.env.user.name, r=reason))
        return self._done(line, _("Rejected. It will not go into the books."))

    @api.model
    def defer(self, line_id, days):
        line = self._line(line_id)
        self._need_officer()
        if int(days) not in DEFER_CHOICES:
            raise UserError(_("Choose tomorrow, 3 days or a week."))
        self.env['ei.work'].snooze(MODEL, line.id, int(days))
        return self._done(line, _("Put aside. It comes back on your list in %s day(s).", int(days)))

    @api.model
    def undefer(self, line_id):
        line = self._line(line_id)
        self.env['ei.work'].unsnooze(MODEL, line.id)
        return self._done(line, _("Back on your list."))

    @api.model
    def ask_evidence(self, line_id, text, user_id=False):
        line = self._line(line_id)
        self._need_officer()
        text = (text or '').strip()
        if len(text) < 5:
            raise UserError(_("Say what you need, for example: Please send the payment slip."))
        who = self.env['res.users']
        if user_id:
            who = self.env['res.users'].browse(int(user_id)).exists()
            if not who or not who.active or who.share or not line.with_user(who).has_access('read'):
                raise UserError(_("That person cannot open this bank line."))
        line.message_post(body=_("Evidence requested by %(u)s: %(t)s", u=self.env.user.name, t=text))
        if who:
            line.activity_schedule('mail.mail_activity_data_todo', summary=_("Evidence needed for bank payment %s", self._money(line.amount, line)),
                                   note=text, user_id=who.id)
        return self._done(line, _("Noted on the line.") if not who else _("Noted on the line and %s was asked.", who.name))
