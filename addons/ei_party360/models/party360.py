"""Party 360: one page per customer / supplier, built ONLY from records the current user may read.

Nothing here writes. Every figure is defined once in `_defs()` together with the domain behind it, so the
page can show the exact records ("Explain this number") and the numbers cannot drift from their drill-down.
A section the user's role cannot read is left out and named in `hidden`, never shown as a false zero.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import format_amount
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

CHAIN_LIMIT = 20
TIMELINE_LIMIT = 30
EVENT_LIMIT = 10          # per record type before merging
SEARCH_LIMIT = 12
LOOSE_CODE_LIMIT = 4      # unlinked old codes shown after the real parties

# Models the page may open a form for (so a crafted RPC cannot be used to open arbitrary records).
OPENABLE = {'res.partner', 'ei.contract', 'ei.da', 'ei.daily.order', 'ei.lifting', 'ei.supplier.intake',
            'ei.bank.import.line', 'ei.parent.statement', 'ei.legacy.code', 'account.move'}

PAYMENT_LABEL = {
    'paid': _lt("Paid"), 'partial': _lt("Partly paid"), 'in_payment': _lt("Payment registered, not yet matched to the bank"),
    'not_paid': _lt("Not paid"), 'reversed': _lt("Reversed"), 'invoicing_legacy': _lt("Not paid"),
}


def _like(term):
    """Escape LIKE wildcards so a typed '_' or '%' is searched literally."""
    return term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


class EiParty360(models.AbstractModel):
    _name = 'ei.party360'
    _description = 'Party 360 page data'

    # ------------------------------------------------------------------ helpers
    def _can(self, model, op='read'):
        return model in self.env and self.env[model].has_access(op)

    def _finance_ok(self):
        """Same role rule as the management dashboard: ledger balances are for finance and management (and the
        read-only auditor), not for every user who happens to be able to open an accounting screen."""
        return self.env['ei.dashboard']._allowed('finance') or self.env.user.has_group('ei_legacy_master.group_ei_auditor')

    def _label(self, rec, field):
        return dict(rec._fields[field]._description_selection(self.env)).get(rec[field], rec[field])

    def _money(self, groups):
        """groups: [(currency, amount)] -> '420,000.00 PKR' (several currencies are never added together)."""
        parts = [format_amount(self.env, amt, cur) for cur, amt in groups if cur]
        return ' + '.join(parts) if parts else format_amount(self.env, 0.0, self.env.company.currency_id)

    @staticmethod
    def _mtl(v):
        return '{:,.3f} MTL'.format(v)

    # ------------------------------------------------------------------ search
    @api.model
    def search_parties(self, term):
        """Find a party by name, contact reference, EXACT legacy code text, nickname or approved alias.
        Runs as the current user: record rules decide what can be found. Codes are matched as text (4.20 != 4.2)."""
        term = (term or '').strip()
        if len(term) < 2:
            return []
        env, parties, loose, seen = self.env, [], [], set()

        def add(partner, why):
            if partner and partner.id not in seen:
                seen.add(partner.id)
                parties.append({'partner_id': partner.id, 'code_id': False, 'title': partner.name,
                                'subtitle': ' · '.join(x for x in (partner.ref, why) if x), 'reason': why})
        if self._can('ei.legacy.code'):
            codes = env['ei.legacy.code'].search(
                ['|', '|', ('legacy_code', '=like', _like(term) + '%'),
                 ('original_name', 'ilike', _like(term)), ('nickname', 'ilike', _like(term))], limit=SEARCH_LIMIT * 2)
            for c in codes:
                partner = env['res.partner'].browse(c.linked_res_id).exists() if c.linked_model == 'res.partner' else None
                if partner:
                    add(partner, _("Old code %s", c.legacy_code))
                else:
                    loose.append({'partner_id': False, 'code_id': c.id, 'title': c.display_name, 'reason': _("Old code"),
                                  'subtitle': _("Old code - not linked to a party yet (an accountant must approve its mapping)")})
        for p in env['res.partner'].search(['|', ('name', 'ilike', _like(term)), ('ref', 'ilike', _like(term))], limit=SEARCH_LIMIT):
            add(p, _("Name"))
        if self._can('ei.partner.alias'):
            for a in env['ei.partner.alias'].search([('alias', 'ilike', _like(term)), ('state', '=', 'approved')], limit=SEARCH_LIMIT):
                add(a.partner_id, _("Also known as %s", a.alias))
        # real parties first; old codes that are not linked to a party yet come last and cannot flood the list
        return (parties + loose[:LOOSE_CODE_LIMIT])[:SEARCH_LIMIT]

    # ------------------------------------------------------------------ the figures (one definition = value + drill-down)
    def _defs(self, p):
        pid, env = p.id, self.env
        on_line = ['|', ('da_id.parent_partner_id', '=', pid), ('customer_id', '=', pid)]
        ledger = [('company_id', 'in', env.companies.ids), ('parent_state', '=', 'posted'), ('reconciled', '=', False),
                  ('partner_id', 'child_of', pid)]
        return [
            # ---- material
            dict(key='m_approved', group='material', model='ei.da.line', label=_("Approved on delivery advices"),
                 basis=_("Approved documents"), measure=('sum', 'mtl', 'mtl'), tone='info',
                 domain=[('state', '=', 'approved')] + on_line,
                 explain=_("Adds up the MTL on every line of every approved delivery advice (DA) where this party is the parent company or the customer.")),
            dict(key='m_ordered', group='material', model='ei.daily.order.line', label=_("Asked for on daily orders"),
                 basis=_("Approved documents"), measure=('sum', 'requested_mtl', 'mtl'), tone='info',
                 domain=[('state', '=', 'approved')] + on_line,
                 explain=_("Adds up the MTL requested on approved daily orders for this party's delivery advices.")),
            dict(key='m_lifted', group='material', model='ei.lifting', label=_("Truly lifted (verified)"),
                 basis=_("Checked by a second person"), measure=('sum', 'verified_mtl', 'mtl'), tone='ok',
                 domain=[('state', '=', 'verified')] + on_line,
                 explain=_("Adds up the verified MTL of truck loadings that someone checked against the gate pass and weighbridge slip. A supplier invoice never counts as lifting.")),
            dict(key='m_remaining', group='material', model='ei.da.line', label=_("Still to lift"),
                 basis=_("Approved minus verified"), measure=('remaining',), tone='warning',
                 domain=[('state', '=', 'approved')] + on_line,
                 explain=_("For each approved DA line: approved MTL minus verified lifted MTL, added up. It is worked out line by line, so an over-lifted line cannot hide a short one.")),
            dict(key='l_to_invoice', group='material', model='ei.lifting', label=_("Delivered, not yet invoiced"),
                 basis=_("Waiting for a person"), measure=('count_sum', 'verified_mtl', 'mtl'), tone='warning',
                 domain=[('invoice_status', '=', 'to_invoice')] + on_line,
                 explain=_("Verified truck loadings that have no customer invoice yet. They are ready to be invoiced.")),
            # ---- documents waiting
            dict(key='d_contracts', group='documents', model='ei.contract', label=_("Active contracts"),
                 basis=_("Approved documents"), measure=('count',), tone='info',
                 domain=[('parent_partner_id', '=', pid), ('state', 'in', ('approved', 'active'))],
                 explain=_("Contracts with this party as parent company that are approved or active.")),
            dict(key='d_das', group='documents', model='ei.da', label=_("Delivery advices to approve"),
                 basis=_("Waiting for a person"), measure=('count',), tone='warning',
                 domain=['|', ('parent_partner_id', '=', pid), ('line_ids.customer_id', '=', pid), ('state', '=', 'under_review')],
                 explain=_("Delivery advices for this party that are under review and need a second person.")),
            dict(key='d_orders', group='documents', model='ei.daily.order', label=_("Daily orders to approve"),
                 basis=_("Waiting for a person"), measure=('count',), tone='warning',
                 domain=[('parent_partner_id', '=', pid), ('state', '=', 'draft')],
                 explain=_("Daily orders for this supplier that are still drafts.")),
            dict(key='d_intake', group='documents', model='ei.supplier.intake', label=_("Supplier invoices with a problem"),
                 basis=_("Waiting for a person"), measure=('count',), tone='danger',
                 domain=[('partner_id', '=', pid), ('state', '=', 'mismatch')],
                 explain=_("Supplier invoices where the quantity, rate or total did not match our records. They are blocked until someone reviews them.")),
            # ---- money (posted books)
            dict(key='f_ar', needs='finance', group='money', model='account.move.line', label=_("They owe us"),
                 basis=_("Posted in the books"), measure=('ledger', 1), tone='warning',
                 domain=ledger + [('account_type', '=', 'asset_receivable')],
                 explain=_("Open receivable items in the posted ledger for this party, in company currency. Draft invoices and unmatched bank lines are NOT included.")),
            dict(key='f_ap', needs='finance', group='money', model='account.move.line', label=_("We owe them"),
                 basis=_("Posted in the books"), measure=('ledger', -1), tone='warning',
                 domain=ledger + [('account_type', '=', 'liability_payable')],
                 explain=_("Open payable items in the posted ledger for this party, in company currency. Supplier invoices still being checked are NOT included.")),
            dict(key='f_invoices', needs='finance', group='money', model='account.move', label=_("Customer invoices issued"),
                 basis=_("Posted in the books"), measure=('moves',), tone='info',
                 domain=[('move_type', 'in', ('out_invoice', 'out_refund')), ('state', '=', 'posted'), ('partner_id', 'child_of', pid)],
                 explain=_("Posted customer invoices and credit notes for this party, in company currency (credit notes count as minus).")),
            # ---- bank evidence
            dict(key='b_in', group='bank', model='ei.bank.import.line', label=_("Bank money received (party confirmed)"),
                 basis=_("Checked by a second person"), measure=('money', 'amount'), tone='ok',
                 domain=[('partner_id', '=', pid), ('amount', '>', 0), ('state', 'in', ('verified', 'posted'))],
                 explain=_("Bank statement lines where a person confirmed this party as the payer. Each line comes from an imported bank statement.")),
            dict(key='b_suggested', group='bank', model='ei.bank.import.line', label=_("Bank money only suggested"),
                 basis=_("Suggestion only - not confirmed"), measure=('money', 'amount'), tone='info',
                 domain=[('suggested_partner_id', '=', pid), ('state', 'in', ('new', 'proposed'))],
                 explain=_("Bank lines the system THINKS belong to this party. Nobody has confirmed them, so they are not counted as received money.")),
            dict(key='p_diff', group='bank', model='ei.parent.statement.line', label=_("Open differences with the parent company"),
                 basis=_("Waiting for a person"), measure=('diff',), tone='warning',
                 domain=[('statement_id.partner_id', '=', pid), ('status', '!=', 'matched'), ('resolution_state', '=', 'open')],
                 explain=_("Lines where the parent company's statement and our books disagree and nobody has resolved it yet. The amount is the total size of the differences.")),
        ]

    def _value(self, d):
        """Return (count, text) for one definition. Runs as the current user."""
        Model, dom, m = self.env[d['model']], d['domain'], d['measure']
        kind = m[0]
        if kind == 'count':
            n = Model.search_count(dom)
            return n, str(n)
        if kind in ('sum', 'count_sum'):
            rows = Model._read_group(dom, aggregates=['__count', '%s:sum' % m[1]])
            n, total = rows[0] if rows else (0, 0.0)
            total = total or 0.0
            text = self._mtl(total)
            if kind == 'count_sum':
                return n, '%s · %s' % (_("1 loading") if n == 1 else _("%s loadings", n), text)
            return n, text
        if kind == 'remaining':
            recs = Model.search(dom)
            total = sum(recs.mapped('remaining_to_lift'))
            return len(recs), self._mtl(total)
        if kind == 'ledger':
            rows = Model._read_group(dom, aggregates=['__count', 'amount_residual:sum'])
            n, total = rows[0] if rows else (0, 0.0)
            return n, self._money([(self.env.company.currency_id, m[1] * (total or 0.0))])
        if kind == 'moves':
            rows = Model._read_group(dom, aggregates=['__count', 'amount_total_signed:sum'])
            n, total = rows[0] if rows else (0, 0.0)
            return n, (_("%(n)s · %(amt)s", n=n, amt=self._money([(self.env.company.currency_id, total or 0.0)])) if n else '0')
        if kind == 'money':
            recs = Model.search_fetch(dom, [m[1], 'currency_id'])   # currency is not stored on bank lines: group in Python
            groups = {}
            for r in recs:
                groups[r.currency_id] = groups.get(r.currency_id, 0.0) + r[m[1]]
            n = len(recs)
            return n, (_("%(n)s · %(amt)s", n=n, amt=self._money(list(groups.items()))) if n else '0')
        if kind == 'diff':
            recs = Model.search(dom)
            groups = {}
            for r in recs:
                groups[r.currency_id] = groups.get(r.currency_id, 0.0) + abs(r.difference)
            n = len(recs)
            return n, (_("%(n)s · %(amt)s", n=n, amt=self._money(list(groups.items()))) if n else '0')
        raise UserError(_("Unknown measure."))

    def _chains_hidden(self, partner):
        return not self._can('ei.da')

    # ------------------------------------------------------------------ chains (contract -> DA -> order -> lifting -> invoice -> payment)
    def _chains(self, p):
        env = self.env
        if not self._can('ei.da'):
            return None
        DA = env['ei.da']
        das = DA.search(['|', ('parent_partner_id', '=', p.id), ('line_ids.customer_id', '=', p.id),
                         ('state', 'in', ('under_review', 'approved', 'fulfilled', 'closed'))],
                        order='date desc, id desc', limit=CHAIN_LIMIT)
        can_order, can_lift = self._can('ei.daily.order.line'), self._can('ei.lifting')
        orders, lifts = {}, {}
        if can_order and das:
            for l in env['ei.daily.order.line'].search([('da_id', 'in', das.ids), ('state', '=', 'approved')]):
                orders[l.da_id.id] = orders.get(l.da_id.id, 0.0) + l.requested_mtl
        if can_lift and das:
            for l in env['ei.lifting'].search([('da_id', 'in', das.ids)]):
                lifts[l.da_id.id] = lifts.get(l.da_id.id, env['ei.lifting']) | l
        rows = []
        for da in das:
            total = da.total_mtl
            ls = lifts.get(da.id, env['ei.lifting'])
            verified = ls.filtered(lambda x: x.state == 'verified')
            drafts = len(ls.filtered(lambda x: x.state == 'draft'))
            lifted = sum(verified.mapped('verified_mtl'))
            invoiced = verified.filtered('invoice_move_id')
            to_invoice = len(verified) - len(invoiced)
            moves = invoiced.mapped('invoice_move_id').filtered(lambda m: m.state == 'posted')
            ordered = orders.get(da.id, 0.0)
            c = da.contract_id
            stages = [
                {'key': 'contract', 'label': _("Contract"), 'text': '%s · %s' % (c.name, self._label(c, 'state')),
                 'tone': 'done' if c.state in ('approved', 'active', 'fulfilled', 'closed') else 'active',
                 'model': 'ei.contract', 'res_id': c.id},
                {'key': 'da', 'label': _("Delivery advice"), 'text': '%s · %s' % (da.name, self._label(da, 'state')),
                 'tone': 'done' if da.state in ('approved', 'fulfilled', 'closed') else 'active',
                 'model': 'ei.da', 'res_id': da.id},
            ]
            if not can_order:
                stages.append({'key': 'order', 'label': _("Daily order"), 'text': _("Not visible to your role"), 'tone': 'hidden'})
            else:
                stages.append({'key': 'order', 'label': _("Daily order"),
                               'text': (_("%(a)s of %(b)s asked for", a=self._mtl(ordered), b=self._mtl(total)) if ordered else _("No order yet")),
                               'tone': 'done' if total and ordered >= total else ('active' if ordered else 'todo')})
            if not can_lift:
                stages.append({'key': 'lift', 'label': _("Lifted"), 'text': _("Not visible to your role"), 'tone': 'hidden'})
                stages.append({'key': 'invoice', 'label': _("Invoiced"), 'text': _("Not visible to your role"), 'tone': 'hidden'})
            else:
                txt = _("%(a)s of %(b)s lifted", a=self._mtl(lifted), b=self._mtl(total)) if lifted else _("Nothing verified yet")
                if drafts:
                    txt += _(" · %s waiting for a check", drafts)
                stages.append({'key': 'lift', 'label': _("Lifted"), 'text': txt,
                               'tone': 'done' if total and lifted >= total else ('active' if lifted or drafts else 'todo')})
                if not verified:
                    stages.append({'key': 'invoice', 'label': _("Invoiced"), 'text': _("Nothing to invoice yet"), 'tone': 'todo'})
                else:
                    stages.append({'key': 'invoice', 'label': _("Invoiced"),
                                   'text': _("%(a)s of %(b)s loadings invoiced", a=len(invoiced), b=len(verified)),
                                   'tone': 'done' if not to_invoice else 'active'})
            # payment comes from Odoo's own posted accounting (a screenshot or a suggestion never counts)
            if not moves:
                stages.append({'key': 'payment', 'label': _("Paid"), 'text': _("Nothing invoiced yet"), 'tone': 'todo'})
            else:
                states = set(moves.mapped('payment_state'))
                if states <= {'paid'}:
                    stages.append({'key': 'payment', 'label': _("Paid"), 'text': str(PAYMENT_LABEL['paid']), 'tone': 'done'})
                else:
                    worst = 'partial' if states & {'partial', 'paid', 'in_payment'} else 'not_paid'
                    stages.append({'key': 'payment', 'label': _("Paid"), 'text': str(PAYMENT_LABEL[worst]), 'tone': 'active' if worst != 'not_paid' else 'todo'})
            rows.append({'da_id': da.id, 'da': da.name, 'total': self._mtl(total), 'stages': stages})
        return rows

    # ------------------------------------------------------------------ timeline
    def _timeline(self, p):
        env, ev, pid = self.env, [], p.id

        def add(date, kind, title, detail, model, rid):
            if date:
                ev.append({'date': fields.Date.to_string(date), 'kind': kind, 'title': title, 'detail': detail,
                           'model': model, 'res_id': rid})
        on_line = ['|', ('da_id.parent_partner_id', '=', pid), ('customer_id', '=', pid)]
        if self._can('ei.contract'):
            for r in env['ei.contract'].search([('parent_partner_id', '=', pid)], order='date desc', limit=EVENT_LIMIT):
                add(r.date, 'contract', _("Contract %s", r.name), self._label(r, 'state'), r._name, r.id)
        if self._can('ei.da'):
            for r in env['ei.da'].search(['|', ('parent_partner_id', '=', pid), ('line_ids.customer_id', '=', pid)], order='date desc', limit=EVENT_LIMIT):
                add(r.date, 'da', _("Delivery advice %s", r.name), '%s · %s' % (self._label(r, 'state'), self._mtl(r.total_mtl)), r._name, r.id)
        if self._can('ei.daily.order'):
            for r in env['ei.daily.order'].search([('parent_partner_id', '=', pid)], order='date desc', limit=EVENT_LIMIT):
                add(r.date, 'order', _("Daily order %s", r.name), self._label(r, 'state'), r._name, r.id)
        if self._can('ei.lifting'):
            for r in env['ei.lifting'].search(on_line, order='date desc', limit=EVENT_LIMIT):
                qty = r.verified_mtl if r.state == 'verified' else r.claimed_mtl
                add(r.date, 'lifting', _("Truck loading, gate pass %s", r.gate_pass_no),
                    '%s · %s' % (self._label(r, 'state'), self._mtl(qty or 0.0)), r._name, r.id)
        if self._can('ei.supplier.intake'):
            for r in env['ei.supplier.intake'].search([('partner_id', '=', pid)], order='invoice_date desc', limit=EVENT_LIMIT):
                add(r.invoice_date, 'intake', _("Supplier invoice %s", r.invoice_number),
                    '%s · %s' % (self._label(r, 'state'), format_amount(env, r.stated_total, r.currency_id)), r._name, r.id)
        if self._can('account.move') and self._finance_ok():
            for r in env['account.move'].search([('move_type', 'in', ('out_invoice', 'out_refund')), ('state', '=', 'posted'),
                                                 ('partner_id', 'child_of', pid)], order='invoice_date desc', limit=EVENT_LIMIT):
                add(r.invoice_date, 'invoice', _("Customer invoice %s", r.name),
                    '%s · %s' % (format_amount(env, r.amount_total, r.currency_id), str(PAYMENT_LABEL.get(r.payment_state, r.payment_state))),
                    r._name, r.id)
        if self._can('ei.bank.import.line'):
            for r in env['ei.bank.import.line'].search(['|', ('partner_id', '=', pid), ('suggested_partner_id', '=', pid)],
                                                       order='date desc', limit=EVENT_LIMIT):
                confirmed = r.partner_id.id == pid
                add(r.date, 'bank', _("Bank line %s", r.ref or r.narration or ''),
                    '%s · %s' % (format_amount(env, r.amount, r.currency_id),
                                 _("Party confirmed") if confirmed else _("Suggested only - not confirmed")), r._name, r.id)
        if self._can('ei.parent.statement'):
            for r in env['ei.parent.statement'].search([('partner_id', '=', pid)], order='date_to desc', limit=5):
                add(r.date_to, 'statement', _("Parent statement %s", r.name), self._label(r, 'state'), r._name, r.id)
        ev.sort(key=lambda e: e['date'], reverse=True)
        return ev[:TIMELINE_LIMIT]

    # ------------------------------------------------------------------ the page
    @api.model
    def get_data(self, partner_id):
        env = self.env
        partner = env['res.partner'].browse(int(partner_id)).exists()
        if not partner:
            raise UserError(_("This party no longer exists."))
        partner.check_access('read')
        hidden, metrics = [], []
        for d in self._defs(partner):
            if not self._can(d['model']) or (d.get('needs') == 'finance' and not self._finance_ok()):
                hidden.append(d['group'])
                continue
            try:
                n, text = self._value(d)
            except AccessError:
                hidden.append(d['group'])
                continue
            tone = d['tone'] if n else ('ok' if d['tone'] in ('warning', 'danger') else 'neutral')
            metrics.append({'key': d['key'], 'group': d['group'], 'label': d['label'], 'basis': d['basis'],
                            'text': text, 'count': n, 'tone': tone, 'explain': d['explain']})
        codes = []
        if self._can('ei.legacy.code'):
            for c in env['ei.legacy.code'].search([('linked_model', '=', 'res.partner'), ('linked_res_id', '=', partner.id)]):
                codes.append({'id': c.id, 'code': c.legacy_code, 'name': c.original_name, 'sheet': c.source_sheet_key,
                              'status': self._label(c, 'verification_status')})
        aliases = []
        if self._can('ei.partner.alias'):
            aliases = env['ei.partner.alias'].search([('partner_id', '=', partner.id), ('state', '=', 'approved')]).mapped('alias')
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        group_labels = (('material', _("Material")), ('documents', _("Documents waiting")), ('money', _("Money in the books")),
                        ('bank', _("Bank and parent company")))
        if self._chains_hidden(partner):
            hidden.append('chains')
        label_of = dict(group_labels, chains=_("From contract to payment"))
        hidden = [label_of[k] for k in label_of if k in set(hidden)]
        return {
            'partner': {'id': partner.id, 'name': partner.name, 'ref': partner.ref or '', 'codes': codes,
                        'aliases': aliases, 'city': partner.city or '', 'phone': partner.phone or '', 'email': partner.email or ''},
            'as_of': now.strftime('%d %b %Y %H:%M'),
            'groups': [{'key': k, 'label': l} for k, l in group_labels],
            'metrics': metrics,
            'chains': self._chains(partner),
            'timeline': self._timeline(partner),
            'hidden': hidden,
        }

    # ------------------------------------------------------------------ clicks
    @api.model
    def open_records(self, partner_id, key):
        partner = self.env['res.partner'].browse(int(partner_id)).exists()
        partner.check_access('read')
        for d in self._defs(partner):
            if d['key'] == key:
                if not self._can(d['model']) or (d.get('needs') == 'finance' and not self._finance_ok()):
                    raise AccessError(_("Your role cannot open these records."))
                return {'type': 'ir.actions.act_window', 'name': '%s - %s' % (partner.name, d['label']),
                        'res_model': d['model'], 'domain': d['domain'],
                        'views': self.env['ei.home']._views_for(d['model']), 'target': 'current'}
        raise UserError(_("Unknown figure."))

    @api.model
    def open_record(self, model, res_id):
        if model not in OPENABLE:
            raise AccessError(_("This record type cannot be opened from here."))
        rec = self.env[model].browse(int(res_id)).exists()
        rec.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': model, 'res_id': rec.id, 'views': [[False, 'form']],
                'target': 'current'}
