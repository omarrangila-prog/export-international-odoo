"""DEMO / UAT data. Run in `odoo shell` on a STAGING database only:   odoo shell -d <db> ... < migration/seed_uat_demo.py

Creates clearly-labelled DEMO records (names start with "DEMO") by acting through real role users, so every control
(maker-checker, approvals) is exercised exactly as in daily use. Also creates one demo login per role (password: demo).
Nothing here is client data. Never run on production."""
from odoo import Command, fields

env = env(su=True)
co = env.company
G = lambda x: env.ref(x).id
ROLES = {
    'demo.importer': ['ei_legacy_master.group_ei_importer'],
    'demo.mapper': ['ei_legacy_master.group_ei_mapping_approver'],
    'demo.bank': ['ei_bank_operations.group_ei_bank_officer'],
    'demo.bankapprover': ['ei_bank_operations.group_ei_bank_approver'],
    'demo.bankposter': ['ei_bank_operations.group_ei_bank_poster'],
    'demo.cash': ['ei_cashbook.group_ei_cash_clerk'],
    'demo.cashapprover': ['ei_cashbook.group_ei_cash_approver'],
    'demo.contracts': ['ei_contract_da.group_ei_contract_staff'],
    'demo.contractapprover': ['ei_contract_da.group_ei_contract_approver', 'ei_daily_orders.group_ei_order_approver',
                              'ei_contract_da.group_ei_da_override'],
    'demo.accountant': ['ei_contract_da.group_ei_formula_approver', 'account.group_account_user'],
    'demo.dispatch': ['ei_material_lifting.group_ei_dispatch_officer'],
    'demo.liftingreviewer': ['ei_material_lifting.group_ei_lifting_reviewer'],
    'demo.invoicing': ['ei_invoice_extensions.group_ei_invoicing'],
    'demo.invoiceapprover': ['ei_invoice_extensions.group_ei_invoice_approver'],
    'demo.recon': ['ei_parent_reconciliation.group_ei_recon_user'],
    'demo.reconapprover': ['ei_parent_reconciliation.group_ei_recon_approver'],
    'demo.ceo': ['ei_management_dashboard.group_ei_management'],
    'demo.finance': ['account.group_account_manager', 'ei_bank_operations.group_ei_bank_approver', 'ei_cashbook.group_ei_cash_approver'],
    'demo.sysadmin': ['base.group_system', 'ei_legacy_master.group_ei_user'],   # administrator with NO business role
}
U = {}
for login, groups in ROLES.items():
    u = env['res.users'].search([('login', '=', login)])
    if not u:
        u = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'DEMO ' + login.split('.')[1].title(), 'login': login, 'password': 'demo', 'email': login + '@example.invalid',
            'company_id': co.id, 'company_ids': [Command.set([co.id])], 'group_ids': [Command.set([G(g) for g in groups])]})
    U[login.split('.')[1]] = u
env['res.users'].search([('login', '=like', 'demo.%')]).write({'action_id': env.ref('ei_ui_theme.action_ei_home').id})
as_ = lambda role, model: env[model].with_user(U[role])

# --- master data
parent = env['res.partner'].search([('name', '=', 'DEMO Parent Steel Mill')]) or env['res.partner'].create({'name': 'DEMO Parent Steel Mill', 'is_company': True})
c1 = env['res.partner'].search([('name', '=', 'DEMO Customer - Rehman Traders')]) or env['res.partner'].create({'name': 'DEMO Customer - Rehman Traders', 'is_company': True})
c2 = env['res.partner'].search([('name', '=', 'DEMO Customer - Noor Steel')]) or env['res.partner'].create({'name': 'DEMO Customer - Noor Steel', 'is_company': True})
inc = env['account.account'].search([('account_type', '=', 'income'), ('company_ids', 'in', co.id)], limit=1)
exp = env['account.account'].search([('account_type', '=', 'expense'), ('company_ids', 'in', co.id)], limit=1)
prod = env['product.product'].search([('name', '=', 'DEMO HR Coil 2mm')]) or env['product.product'].create({
    'name': 'DEMO HR Coil 2mm', 'uom_id': env.ref('uom.product_uom_ton').id, 'taxes_id': [Command.set([])], 'supplier_taxes_id': [Command.set([])],
    'property_account_income_id': inc.id, 'property_account_expense_id': exp.id})
bank = env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', co.id)], limit=1) or env['account.journal'].create({'name': 'DEMO Main Bank', 'type': 'bank', 'code': 'DEMB1', 'company_id': co.id})
bank2 = env['account.journal'].search([('code', '=', 'DEMB2'), ('company_id', '=', co.id)]) or env['account.journal'].create({'name': 'DEMO Meezan Bank', 'type': 'bank', 'code': 'DEMB2', 'company_id': co.id})
cash = env['account.journal'].search([('type', '=', 'cash'), ('company_id', '=', co.id)], limit=1) or env['account.journal'].create({'name': 'DEMO Cash box', 'type': 'cash', 'code': 'DEMC', 'company_id': co.id})
att = lambda rec: env['ir.attachment'].create({'name': 'scan.txt', 'res_model': rec._name, 'res_id': rec.id, 'raw': b'DEMO scanned document'})
formula = env.ref('ei_contract_da.formula_example_mill_rate')
if formula.state == 'draft':
    formula.with_user(U['accountant']).action_approve()

# --- contract (maker -> reviewer -> approver) and DAs
if not env['ei.contract'].search([('contract_ref', '=', 'DEMO/ISL/001')]):
    ct = as_('contracts', 'ei.contract').create({
        'parent_partner_id': parent.id, 'contract_ref': 'DEMO/ISL/001', 'contract_type': 'commission',
        'valid_from': fields.Date.today().replace(month=1, day=1), 'valid_to': fields.Date.today().replace(month=12, day=31),
        'line_ids': [Command.create({'product_id': prod.id, 'grade': 'HR 2.0 mm', 'ordered_mtl': 200, 'purchase_rate': 200000,
                                     'sale_rate': 210000, 'formula_id': formula.id, 'basic_rate': 210000,
                                     'param_ids': [Command.create({'key': 'deduction_pct', 'value': '1.32'})]})]})
    att(ct); ct.with_user(U['contracts']).action_review(); ct.with_user(U['contractapprover']).action_approve()
    ct.with_user(U['contracts']).action_activate()
    ct.line_ids.with_user(U['contractapprover']).action_set_ownership('direct_dispatch', 'DEMO: mill dispatches to customer')
    ct2 = as_('contracts', 'ei.contract').create({
        'parent_partner_id': parent.id, 'contract_ref': 'DEMO/HAD/014', 'contract_type': 'end_coils',
        'line_ids': [Command.create({'product_id': prod.id, 'grade': 'End coils', 'ordered_mtl': 60, 'purchase_rate': 150000, 'sale_rate': 158000})]})
    att(ct2); ct2.with_user(U['contracts']).action_review()
    def mkda(name, mtl, cust, approve=True):
        d = as_('contracts', 'ei.da').create({'name': name, 'parent_partner_id': parent.id, 'contract_id': ct.id,
            'line_ids': [Command.create({'contract_line_id': ct.line_ids.id, 'mtl': mtl, 'customer_id': cust.id})]})
        att(d); d.with_user(U['contracts']).action_review()
        if approve:
            d.with_user(U['contractapprover']).action_approve()
        return d
    da1, da2, da3 = mkda('DA-DEMO-5501', 40, c1), mkda('DA-DEMO-5502', 25, c2), mkda('DA-DEMO-5503', 30, c1, approve=False)
    # a second supplier with an approved DA that has NO order yet (lets the browser suite press "Generate Daily Order")
    parent2 = env['res.partner'].search([('name', '=', 'DEMO Parent Steel Mill 2')]) or env['res.partner'].create({'name': 'DEMO Parent Steel Mill 2', 'is_company': True})
    ct3 = as_('contracts', 'ei.contract').create({
        'parent_partner_id': parent2.id, 'contract_ref': 'DEMO/ISL/002', 'contract_type': 'local_direct',
        'line_ids': [Command.create({'product_id': prod.id, 'grade': 'HR 3.0 mm', 'ordered_mtl': 50, 'purchase_rate': 200000, 'sale_rate': 210000})]})
    att(ct3); ct3.with_user(U['contracts']).action_review(); ct3.with_user(U['contractapprover']).action_approve(); ct3.with_user(U['contracts']).action_activate()
    da4 = as_('contracts', 'ei.da').create({'name': 'DA-DEMO-6601', 'parent_partner_id': parent2.id, 'contract_id': ct3.id,
        'line_ids': [Command.create({'contract_line_id': ct3.line_ids.id, 'mtl': 20, 'customer_id': c2.id})]})
    att(da4); da4.with_user(U['contracts']).action_review(); da4.with_user(U['contractapprover']).action_approve()
    order = env['ei.daily.order'].with_user(U['contracts']).generate_from_da(da1)
    env['ei.daily.order'].with_user(U['contracts']).generate_from_da(da2)
    order.with_user(U['contractapprover']).action_approve()
    # trucks
    def truck(da, n, mtl, verify):
        l = as_('dispatch', 'ei.lifting').create({'da_line_id': da.line_ids.id, 'vehicle_no': 'TKA-%s' % n, 'gate_pass_no': 'GP-DEMO-%s' % n, 'claimed_mtl': mtl})
        att(l)
        if verify:
            l.with_user(U['liftingreviewer']).action_verify()
        return l
    truck(da1, 101, 12, True); truck(da1, 102, 8, True); truck(da2, 103, 10, False)
    # supplier invoices: one good, one with a wrong rate
    def intake(no, qty, rate):
        i = as_('invoicing', 'ei.supplier.intake').create({
            'partner_id': parent.id, 'invoice_number': no, 'invoice_date': fields.Date.today(), 'stated_total': qty * rate,
            'line_ids': [Command.create({'da_line_id': da1.line_ids.id, 'order_line_id': order.line_ids.filtered(lambda l: l.da_id == da1).id, 'received_mtl': qty, 'unit_rate': rate})]})
        att(i); i.action_check(); return i
    good = intake('DEMO-SUP-9001', 12, 200000); good.with_user(U['invoicing']).action_create_bill(); good.bill_id.action_post()
    intake('DEMO-SUP-9002', 8, 205000)
    # invoice one lifting to a customer (draft -> posted)
    lift = env['ei.lifting'].search([('gate_pass_no', '=', 'GP-DEMO-101')])
    w = env['ei.invoice.wizard'].with_user(U['invoicing']).with_context(active_model='ei.lifting', active_ids=lift.ids).create({'post': True})
    w.action_create()

# --- cash book
cat = env['ei.cash.category'].search([('name', '=', 'DEMO Office expenses')]) or env['ei.cash.category'].create({'name': 'DEMO Office expenses', 'account_id': exp.id})
if not env['ei.cash.voucher'].search([('description', '=like', 'DEMO%')]):
    def voucher(desc, amt, final):
        v = as_('cash', 'ei.cash.voucher').create({'journal_id': cash.id, 'kind': 'payment', 'amount': amt, 'description': desc, 'category_id': cat.id})
        att(v)
        if final in ('submitted', 'posted'):
            v.with_user(U['cash']).action_submit()
        if final == 'posted':
            v.with_user(U['cashapprover']).action_approve()
    voucher('DEMO tea and stationery', 1850, 'posted'); voucher('DEMO courier charges', 4200, 'submitted'); voucher('DEMO driver food', 900, 'draft')

# --- bank: balance check + a statement in review
today = fields.Date.today()
env['ei.bank.balance.check'].with_user(U['bankapprover']).create({'journal_id': bank.id, 'bank_balance': 0, 'date': today})
env['ei.partner.alias'].create({'partner_id': c1.id, 'alias': 'REHMAN TRADERS', 'state': 'approved'})
if not env['ei.bank.import'].search([('filename', '=', 'demo_statement.csv')]):
    csv = ("Date,Description,Reference,Debit,Credit,Balance\n"
           "%(d)s,RAAST FROM REHMAN TRADERS KHI,TX7001,,420000,420000\n"
           "%(d)s,CASH DEPOSIT UNKNOWN,TX7002,,150000,570000\n"
           "%(d)s,CHEQUE 556677 PAID,,35000,,535000\n" % {'d': today.strftime('%d/%m/%Y')}).encode()
    imp = env['ei.bank.import'].with_user(U['bank']).import_file(bank, 'demo_statement.csv', csv, 0, 535000)
    imp.with_user(U['bank']).action_suggest()

# --- parent statement
if not env['ei.parent.statement'].search([('filename', '=', 'demo_parent_stmt.csv')]):
    s = "Invoice No,Date,Amount,Tax\nDEMO-SUP-9001,%s,2400000,0\nDEMO-SUP-9002,%s,1640000,0\nDEMO-SUP-9003,%s,500000,0\n" % ((today.strftime('%d/%m/%Y'),) * 3)
    st = env['ei.parent.statement'].with_user(U['recon']).import_file(parent, today.replace(day=1), today, 'demo_parent_stmt.csv', s.encode(), control_total=4540000)
    st.with_user(U['recon']).action_match()
env.cr.commit()
print('DEMO data ready. Demo logins (password demo):', ', '.join(sorted(ROLES)))
