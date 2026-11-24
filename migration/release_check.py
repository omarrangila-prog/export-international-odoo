"""READ-ONLY release check. Changes nothing. Run in the Odoo shell of staging or Production before and after an update:

    CHECKERS="Full Name One,Full Name Two" odoo shell -d <db> --no-http < migration/release_check.py      (Odoo.sh: the web shell)

Prints: company currency and journal items (PKR), the Odoo subscription status, module versions, the approval policy and who
holds the approver roles, whether each named checker is exactly one existing user (no password involved), the purchase / P&L
code pairs, and which mills use which approved feeding formula."""
import os

P = lambda *a: print(*a)
P('== database', env.cr.dbname)
icp = env['ir.config_parameter'].sudo()
P('\n== Odoo subscription')
for k in ('database.expiration_date', 'database.expiration_reason', 'database.enterprise_code'):
    v = icp.get_str(k) or ''
    P('  %-32s %s' % (k, ('***' + v[-4:]) if k.endswith('code') and v else (v or '(empty)')))

P('\n== company currency (PKR only)')
for co in env['res.company'].sudo().search([]):
    n = env['account.move.line'].sudo().search_count([('company_id', '=', co.id)])
    P('  %-40s currency %s  journal items %s  %s' % (co.name, co.currency_id.name, n,
      'OK' if co.currency_id.name == 'PKR' else ('the update switches it to PKR (no journal items)' if not n else 'NOT PKR: see docs/deploy_currency_plan.md')))

P('\n== module versions')
for m in env['ir.module.module'].sudo().search([('name', 'in', ('export_international', 'ei_da_feeding', 'ei_contract_da')), ('state', '=', 'installed')]):
    P('  %-24s %s' % (m.name, m.latest_version))

P('\n== approval policy')
pol = env['ei.approval.policy']
P('  maker-checker (no self-approval):', icp.get_bool('ei_legacy_master.enforce_maker_checker'))
P('  approval on for DA / order / lifting / cash / daybook:', [pol.flow_on(f) for f in ('da', 'order', 'lifting', 'cash', 'daybook')])
appr = env.ref('ei_contract_da.group_ei_contract_approver', raise_if_not_found=False)
if appr:
    holders = appr.all_user_ids.filtered(lambda u: u.active and not u.share)
    P('  users who can approve a DA: %s %s' % (len(holders), sorted(holders.mapped('name'))[:15]))
rules = env['ei.approval.rule'].sudo().search([('name', '=', 'Client checkers')])
P('  "Client checkers" rules:', {r.flow: r.approver_user_ids.mapped('name') for r in rules} or 'none')
for who in [x.strip() for x in os.environ.get('CHECKERS', '').split(',') if x.strip()]:
    U = env['res.users'].sudo()
    u = U.search([('login', '=', who)], limit=1) or U.search([('name', '=ilike', who), ('share', '=', False)])
    P('  checker %-28s %s' % (repr(who), ('OK: user %s (login %s)' % (u.name, u.login)) if len(u) == 1 else
                                  ('NOT FOUND' if not u else 'AMBIGUOUS: %s users have this name' % len(u))))

P('\n== purchase / P&L code pairs')
if 'ei.code.pair' in env:
    CP = env['ei.code.pair'].sudo()
    P('  approved %s  suggested %s  proposed by use %s  rejected %s' % tuple(CP.search_count([('state', '=', s)]) for s in ('approved', 'suggested', 'proposed', 'rejected')))
else:
    P('  (not installed yet)')

P('\n== feeding formulas of the mills')
for m in env['res.partner'].sudo().search([('ei_is_supplier_mill', '=', True)]):
    f = m.ei_feeding_formula_id
    P('  %-36s %s' % (m.name, ('%s v%s %s' % (f.code, f.version, f.state)) if f else 'no formula: only Direct can be used'))
