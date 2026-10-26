"""DEMO history for the Overview: about eight weeks of customer invoices, bank receipts and verified truck loadings, so the cards,
the comparison with the previous period and the ageing have something real to show. Run AFTER seed_uat_demo.py, on a STAGING
database only:   ei_shell -d <db> < migration/seed_dashboard_history.py

Everything is labelled DEMO (customers start with "DEMO", invoices carry the reference "DEMO history") and is created by acting
through the real role users, so maker-checker is exercised exactly as in daily use: the officer who imports and verifies is not the
approver, and the approver is not the poster. Deterministic (fixed seed) and idempotent. Nothing here is client data."""
import random
from datetime import timedelta

from odoo import Command, fields

env = env(su=True)  # noqa: F821  (provided by odoo shell)
co = env.company
today = fields.Date.today()
U = {login.split('.')[1]: env['res.users'].search([('login', '=', login)]) for login in (
    'demo.bank', 'demo.bankapprover', 'demo.bankposter', 'demo.dispatch', 'demo.liftingreviewer')}
if not all(U.values()):
    raise SystemExit('Run seed_uat_demo.py first (the demo role users do not exist).')
if env['account.move'].search_count([('ref', '=', 'DEMO history')]):
    print('DEMO history already present: nothing to do')
    raise SystemExit(0)

rng = random.Random(7)
bank = env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', co.id)], limit=1)
inc = env['account.account'].search([('account_type', '=', 'income'), ('company_ids', 'in', co.id)], limit=1)
partner = lambda name: env['res.partner'].search([('name', '=', name)], limit=1) or env['res.partner'].create({'name': name, 'is_company': True})
customers = [partner('DEMO Customer - Rehman Traders'), partner('DEMO Customer - Noor Steel'), partner('DEMO Customer - Indus Metals'),
             partner('DEMO Customer - Sindh Builders'), partner('DEMO Customer - Al Ameen Rebar')]
ALIASES = {'DEMO Customer - Rehman Traders': 'REHMAN TRADERS', 'DEMO Customer - Noor Steel': 'NOOR STEEL', 'DEMO Customer - Indus Metals': 'INDUS METALS',
           'DEMO Customer - Sindh Builders': 'SINDH BUILDERS', 'DEMO Customer - Al Ameen Rebar': 'AL AMEEN REBAR'}
for c in customers:
    a = env['ei.partner.alias'].search([('partner_id', '=', c.id), ('alias', '=', ALIASES[c.name])])
    if not a:
        env['ei.partner.alias'].create({'partner_id': c.id, 'alias': ALIASES[c.name], 'state': 'approved'})

# ---- customer invoices: busier in the last two weeks than in the two before, as a growing business would be
plan = [(d, 1) for d in (1, 2, 3, 5, 6, 8, 9, 10, 12, 13)] + [(d, 1) for d in (15, 17, 18, 21, 23, 25, 27)] + [(d, 1) for d in range(29, 56, 3)]
invoices = []
for days_ago, _n in plan:
    c = rng.choice(customers)
    amount = rng.choice([315000, 420000, 525000, 630000, 735000, 840000, 1050000, 1260000]) + rng.choice([0, 0, 5000, 12500])
    date = today - timedelta(days=days_ago)
    m = env['account.move'].create({
        'move_type': 'out_invoice', 'partner_id': c.id, 'invoice_date': date, 'invoice_date_due': date + timedelta(days=30), 'ref': 'DEMO history',
        'invoice_line_ids': [Command.create({'name': 'DEMO HR coil, steel trading', 'quantity': 1, 'price_unit': amount, 'tax_ids': [Command.set([])], 'account_id': inc.id})]})
    m.action_post()
    invoices.append((m, days_ago))

# ---- bank receipts for most invoices that are more than two weeks old, through the real statement flow
receipts = []
for m, days_ago in invoices:
    if days_ago >= 16 and rng.random() < 0.72:
        pay_date = max(m.invoice_date + timedelta(days=rng.randint(6, 24)), today - timedelta(days=55))
        receipts.append((min(pay_date, today - timedelta(days=1)), m))
receipts.sort(key=lambda r: (r[0], r[1].id))
if receipts:
    opening = bank._ei_ledger_balance(receipts[0][0], inclusive=False)
    running, rows = opening, ['Date,Description,Reference,Debit,Credit,Balance']
    for i, (d, m) in enumerate(receipts, 1):
        running += m.amount_total
        rows.append('%s,RAAST FROM %s KHI,HIST%03d,,%s,%s' % (d.strftime('%d/%m/%Y'), ALIASES[m.partner_id.name], i, m.amount_total, running))
    batch = env['ei.bank.import'].with_user(U['bank']).import_file(bank, 'demo_history.csv', ('\n'.join(rows) + '\n').encode(), opening, running)
    batch.with_user(U['bank']).action_suggest()
    by_seq = {l.sequence: l for l in batch.line_ids}
    for seq, (d, m) in enumerate(receipts, 1):
        line = by_seq[seq]
        line.with_user(U['bank']).action_verify_partner(m.partner_id, 'DEMO history: approved bank name')
        env['ei.bank.allocation'].with_user(U['bank']).create({'line_id': line.id, 'invoice_id': m.id, 'amount': m.amount_total})
    batch.with_user(U['bankapprover']).write({'variance_note': 'DEMO history'}) if batch.issues else None
    batch.with_user(U['bankapprover']).action_approve()
    batch.with_user(U['bankposter']).action_post()

# ---- truck loadings against the approved delivery advices, spread over the last month and verified by a second person
da = env['ei.da'].search([('name', '=', 'DA-DEMO-5501'), ('state', '=', 'approved')], limit=1)
if da:
    for n, (days_ago, mtl) in enumerate([(26, 2.5), (22, 2), (19, 3), (14, 1.5), (11, 2.5), (7, 2), (4, 3), (2, 1.5)], 1):
        lift = env['ei.lifting'].with_user(U['dispatch']).create({
            'da_line_id': da.line_ids[:1].id, 'vehicle_no': 'TKH-%s' % (200 + n), 'gate_pass_no': 'GP-DEMO-H%s' % n, 'claimed_mtl': mtl,
            'date': today - timedelta(days=days_ago)})
        env['ir.attachment'].create({'name': 'scan.txt', 'res_model': 'ei.lifting', 'res_id': lift.id, 'raw': b'DEMO scanned document'})
        lift.with_user(U['liftingreviewer']).action_verify()
env.cr.commit()
print('DEMO history ready: %s invoices, %s receipts, truck loadings verified.' % (len(invoices), len(receipts)))
