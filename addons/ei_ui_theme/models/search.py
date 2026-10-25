"""Universal search: one box for parties, old codes, contracts, DAs, orders, truck loadings, invoices and bank references.

Runs as the current user: a record the user may not read is never returned, so nothing hidden can leak through the
search box or its cache. The text is escaped before it reaches the database (Odoo's ilike treats % and _ as wildcards).
Old codes are matched as TEXT (1.3 never finds 1.03).
"""
from odoo import api, fields, models, _
from odoo.tools.misc import format_amount

PER_GROUP = 5
TOTAL = 30
MIN_CHARS = 2


def _like(term):
    return term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


class EiSearch(models.AbstractModel):
    _name = 'ei.search'
    _description = 'Universal search'

    def _can(self, model):
        return model in self.env and self.env[model].has_access('read')

    def _st(self, rec, field='state'):
        """The readable label of a status, e.g. 'Approved' instead of 'approved'."""
        return dict(rec._fields[field]._description_selection(self.env)).get(rec[field], rec[field])

    # ------------------------------------------------------------------ parties and old codes (shared with Party 360)
    @api.model
    def parties(self, term, limit=12, loose_limit=4):
        """Real parties first; old codes not linked to a party yet come last and are capped."""
        env, parties, loose, seen = self.env, [], [], set()
        t = _like(term)

        def add(partner, why):
            if partner and partner.id not in seen:
                seen.add(partner.id)
                parties.append({'partner_id': partner.id, 'code_id': False, 'title': partner.name,
                                'subtitle': ' · '.join(x for x in (partner.ref, why) if x), 'reason': why})
        if self._can('ei.legacy.code'):
            codes = env['ei.legacy.code'].search(['|', '|', ('legacy_code', '=like', t + '%'), ('original_name', 'ilike', t),
                                                  ('nickname', 'ilike', t)], limit=limit * 2)
            for c in codes:
                partner = env['res.partner'].browse(c.linked_res_id).exists() if c.linked_model == 'res.partner' else None
                if partner:
                    add(partner, _("Old code %s", c.legacy_code))
                else:
                    loose.append({'partner_id': False, 'code_id': c.id, 'title': c.display_name, 'reason': _("Old code"),
                                  'subtitle': _("Old code - not linked to a party yet (an accountant must approve its mapping)")})
        for p in env['res.partner'].search(['|', ('name', 'ilike', t), ('ref', 'ilike', t)], limit=limit):
            add(p, _("Name"))
        if self._can('ei.partner.alias'):
            for a in env['ei.partner.alias'].search([('alias', 'ilike', t), ('state', '=', 'approved')], limit=limit):
                add(a.partner_id, _("Also known as %s", a.alias))
        return (parties + loose[:loose_limit])[:limit]

    # ------------------------------------------------------------------ everything else
    def _hits(self, model, domain, group, title, subtitle, icon):
        if not self._can(model):
            return []
        return [{'group': group, 'icon': icon, 'model': model, 'res_id': r.id, 'title': title(r), 'subtitle': subtitle(r)}
                for r in self.env[model].search(domain, limit=PER_GROUP, order='write_date desc, id desc')]

    @api.model
    def search(self, term):
        term = (term or '').strip()
        if len(term) < MIN_CHARS:
            return {'term': term, 'groups': [], 'total': 0}
        env, t = self.env, _like(term)
        out = []
        # parties + old codes
        for r in self.parties(term, limit=PER_GROUP + 3):
            if r['partner_id']:
                out.append({'group': _("Customers and suppliers"), 'icon': 'party', 'model': 'ei.party360', 'res_id': r['partner_id'],
                            'title': r['title'], 'subtitle': r['subtitle']})
            else:
                out.append({'group': _("Old codes"), 'icon': 'code', 'model': 'ei.legacy.code', 'res_id': r['code_id'],
                            'title': r['title'], 'subtitle': r['subtitle']})
        out += self._hits('ei.contract', ['|', ('name', 'ilike', t), ('contract_ref', 'ilike', t)], _("Contracts"),
                          lambda r: r.name, lambda r: '%s · %s · %s' % (r.contract_ref, r.parent_partner_id.name, self._st(r)), 'contract')
        out += self._hits('ei.da', [('name', 'ilike', t)], _("Delivery advices"),
                          lambda r: r.name, lambda r: '%s · %s · %.3f MTL' % (r.parent_partner_id.name, self._st(r), r.total_mtl), 'da')
        out += self._hits('ei.daily.order', ['|', ('name', 'ilike', t), ('line_ids.invoice_ref', 'ilike', t)], _("Daily orders"),
                          lambda r: r.name, lambda r: '%s · %s' % (r.parent_partner_id.name, self._st(r)), 'order')
        out += self._hits('ei.lifting', ['|', '|', '|', ('name', 'ilike', t), ('gate_pass_no', 'ilike', t), ('vehicle_no', 'ilike', t),
                                         ('weighbridge_no', 'ilike', t)], _("Truck loadings"),
                          lambda r: '%s · gate pass %s' % (r.name, r.gate_pass_no),
                          lambda r: '%s · %s · %.3f MTL' % (r.vehicle_no, r.da_id.name, r.verified_mtl or r.claimed_mtl or 0.0), 'truck')
        out += self._hits('ei.supplier.intake', ['|', ('name', 'ilike', t), ('invoice_number', 'ilike', t)], _("Supplier invoices"),
                          lambda r: '%s · %s' % (r.invoice_number, r.partner_id.name),
                          lambda r: '%s · %s' % (self._st(r), format_amount(env, r.stated_total, r.currency_id)), 'bill')
        # customer invoices: only for finance roles (same rule as the ledger figures on Home)
        if self._can('account.move') and env['ei.dashboard']._allowed('finance'):
            out += self._hits('account.move', [('move_type', 'in', ('out_invoice', 'out_refund')), ('state', '=', 'posted'),
                                               '|', ('name', 'ilike', t), ('ref', 'ilike', t)], _("Customer invoices"),
                              lambda r: r.name, lambda r: '%s · %s' % (r.partner_id.name or '', format_amount(env, r.amount_total, r.currency_id)), 'invoice')
        out += self._hits('ei.bank.import.line', ['|', ('ref', 'ilike', t), ('narration', 'ilike', t)], _("Bank payments"),
                          lambda r: '%s %s' % (r.ref or '', r.narration or ''),
                          lambda r: '%s · %s · %s' % (r.date, format_amount(env, r.amount, r.currency_id), self._st(r)), 'bank')
        out += self._hits('ei.cash.voucher', ['|', ('name', 'ilike', t), ('description', 'ilike', t)], _("Cash vouchers"),
                          lambda r: '%s · %s' % (r.name, r.description or ''),
                          lambda r: '%s · %s' % (self._st(r), format_amount(env, r.amount, r.currency_id)), 'cash')
        out += self._hits('ei.parent.statement', [('name', 'ilike', t)], _("Parent statements"),
                          lambda r: r.name, lambda r: '%s · %s to %s' % (r.partner_id.name, r.date_from, r.date_to), 'statement')
        out = out[:TOTAL]
        groups = []
        for hit in out:
            g = next((x for x in groups if x['label'] == hit['group']), None)
            if not g:
                groups.append(g := {'label': hit['group'], 'hits': []})
            g['hits'].append({k: v for k, v in hit.items() if k != 'group'})
        return {'term': term, 'groups': groups, 'total': len(out)}

    @api.model
    def open(self, model, res_id):
        """Where a search hit leads. Parties open Party 360; everything else opens its own form."""
        if model == 'ei.party360':
            return {'type': 'ir.actions.client', 'tag': 'ei_party360', 'name': _("Party 360"), 'params': {'partner_id': int(res_id)}}
        allowed = {'ei.legacy.code', 'ei.contract', 'ei.da', 'ei.daily.order', 'ei.lifting', 'ei.supplier.intake', 'account.move',
                   'ei.bank.import.line', 'ei.cash.voucher', 'ei.parent.statement'}
        from odoo.exceptions import AccessError
        if model not in allowed:
            raise AccessError(_("This kind of record cannot be opened from search."))
        rec = self.env[model].browse(int(res_id)).exists()
        rec.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': model, 'res_id': rec.id, 'views': [(False, 'form')], 'target': 'current'}
