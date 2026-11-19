"""READ-ONLY check before any change of the company's accounting currency. Changes nothing.

    odoo shell -c /etc/odoo/odoo.conf -d <db> --no-http < migration/currency_check.py      (Odoo.sh: the web shell, same input)

Prints, per company: its currency, the journal items and entries that exist (posted / draft, by currency, first and last date),
documents of the Export International screens by currency, and whether Odoo would accept a currency change now.
"""
from collections import Counter

pkr = env.ref('base.PKR')
print('PKR active:', pkr.active)
for co in env['res.company'].sudo().search([]):
    print('\n== company %s (id %s): accounting currency %s' % (co.name, co.id, co.currency_id.name))
    AML = env['account.move.line'].sudo()
    Move = env['account.move'].sudo()
    n_lines = AML.search_count([('company_id', '=', co.id)])
    print('journal items:', n_lines)
    for state in ('posted', 'draft', 'cancel'):
        moves = Move.search([('company_id', '=', co.id), ('state', '=', state)])
        if moves:
            dates = sorted(moves.mapped('date'))
            print('  %-7s entries: %5d  first %s  last %s  by currency %s  by type %s' % (
                state, len(moves), dates[0], dates[-1], dict(Counter(m.currency_id.name for m in moves)), dict(Counter(m.move_type for m in moves))))
    rates = env['res.currency.rate'].sudo().search_count([('company_id', 'in', [co.id, False])])
    print('currency rates on file:', rates)
    for model in ('ei.da', 'ei.contract', 'ei.daily.order', 'ei.lifting', 'ei.cash.voucher', 'ei.daybook.entry'):
        if model in env:
            recs = env[model].sudo().search([('company_id', '=', co.id)] if 'company_id' in env[model]._fields else [])
            cur = Counter(r.currency_id.name for r in recs) if 'currency_id' in env[model]._fields else '-'
            print('  %-18s %5d  currency %s' % (model, len(recs), dict(cur) if cur != '-' else cur))
    print('Odoo accepts a currency change now:', 'yes (no journal items)' if not n_lines else 'NO - journal items exist; see docs/deploy_currency_plan.md')
