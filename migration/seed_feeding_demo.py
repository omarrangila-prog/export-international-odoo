"""DEMO data for the DA feeding desk. Run on a STAGING database only, after seed_uat_demo.py:
    odoo shell -d <db> ... < migration/seed_feeding_demo.py

- two DEMO customer codes (D.01, D.02) in a DEMO batch, verified by the demo mapping approver and linked to the demo customers,
  so a fed coil can go all the way to approval on staging (the client's real codes stay unverified, as they are);
- DEMO parties for the feeding entry: the DEMO mill as Supplier (Purchase From) and a DEMO Buying Entity as Purchase (IN);
- one approved DEMO DA fed through the desk with three coils (normal sale, purchase with CN, loss sale), so the feeding
  history and the credit note register have rows to show.
Every name starts with DEMO. Nothing here is client data."""
from datetime import timedelta

from odoo import Command, fields

env = env(su=True)
co = env.company
U = {u.login.split('.')[1]: u for u in env['res.users'].search([('login', '=like', 'demo.%')])}
c1 = env['res.partner'].search([('name', '=', 'DEMO Customer - Rehman Traders')], limit=1)
c2 = env['res.partner'].search([('name', '=', 'DEMO Customer - Noor Steel')], limit=1)
parent = env['res.partner'].search([('name', '=', 'DEMO Parent Steel Mill')], limit=1)
prod = env['product.product'].search([('name', '=', 'DEMO HR Coil 2mm')], limit=1)
today = fields.Date.today()
att = lambda rec: env['ir.attachment'].create({'name': 'DEMO_DA_scan.txt', 'res_model': rec._name, 'res_id': rec.id, 'raw': b'DEMO scanned DA'})

# ---- DEMO customer codes, verified and linked (through the controlled actions)
Code = env['ei.legacy.code']
if not Code.search([('legacy_code', '=', 'D.01'), ('source_sheet_key', '=', 'CUSTOMER')]):
    batch = env['ei.import.batch'].create({'name': 'DEMO codes for the feeding desk'})
    for code, cust in (('D.01', c1), ('D.02', c2)):
        c = Code.create({'legacy_code': code, 'source_sheet': 'CUSTOMER', 'source_sheet_key': 'CUSTOMER', 'source_row': 0,
                         'original_name': cust.name.upper(), 'nickname': cust.name.split(' - ')[-1].split()[0].upper() + '.D',
                         'batch_id': batch.id, 'proposed_target_type': 'res_partner', 'verification_status': 'proposed'})
        c.with_user(U['mapper']).action_approve('res_partner', 'DEMO: verified for the feeding desk')
        c.with_context(ei_system_write=True).write({'linked_model': 'res.partner', 'linked_res_id': cust.id})
d01 = Code.search([('legacy_code', '=', 'D.01'), ('source_sheet_key', '=', 'CUSTOMER')])

# ---- DEMO parties for the one-screen feeding entry: Supplier (Purchase From) -> Purchase (IN) -> Sold (OUT). PKR only.
formula = env.ref('ei_contract_da.formula_isl_asml_dealer_net')
parent.write({'ei_is_supplier_mill': True, 'ei_feeding_formula_id': formula.id if formula.state == 'approved' else False})
if not env['res.partner'].search([('name', '=', 'DEMO Buying Entity')]):
    env['res.partner'].create({'name': 'DEMO Buying Entity', 'is_company': True, 'ei_is_purchase_in': True})

# ---- one approved DEMO DA fed coil by coil through the desk
if not env['ei.da'].search([('name', '=', 'DA-DEMO-FEED-1')]):
    isl = env['ei.contract'].search([('contract_ref', '=', 'DEMO/ISL/001')], limit=1)
    desk = env['ei.feeding.desk'].with_user(U['contracts'])
    da_id = desk.da_create({'contract_id': isl.id, 'name': 'DA-DEMO-FEED-1', 'date': fields.Date.to_string(today - timedelta(days=2)),
                            'order_datetime': fields.Date.to_string(today - timedelta(days=2)) + ' 16:03',
                            'ship_date': fields.Date.to_string(today - timedelta(days=2)), 'printed_customer': 'M/S DEMO CUSTOMER - REHMAN TRADERS'})
    da = env['ei.da'].browse(da_id); att(da)
    base = {'contract_line_id': isl.line_ids.id, 'grade': 'P', 'basic_rate': '210000', 'customer_id': c1.id, 'customer_code_id': d01.id}
    desk.save_line(da_id, False, dict(base, coil_no='DEMO-COIL-01', weight_kg='4574', method='normal_sale', sale_offset='-1000'))
    desk.save_line(da_id, False, dict(base, coil_no='DEMO-COIL-02', weight_kg='5120', method='purchase_with_cn', sale_offset='0',
                                      cn_amount='1000', cn_text='DEMO CN 1,000 on this coil'))
    desk.save_line(da_id, False, dict(base, coil_no='DEMO-COIL-03', weight_kg='3980', method='loss_sale', sale_offset='-10000',
                                      loss_reason='DEMO: clearing an old coil'))
    da.with_user(U['contracts']).action_review()
    da.with_user(U['contractapprover']).action_approve()
# ---- one DEMO training login that can do every daily task (used for the training film); password: demo
TRAINER_GROUPS = ['ei_contract_da.group_ei_contract_staff', 'ei_material_lifting.group_ei_dispatch_officer',
                  'ei_invoice_extensions.group_ei_invoicing', 'ei_cashbook.group_ei_cash_clerk', 'account.group_account_user',
                  'ei_bank_operations.group_ei_bank_officer', 'ei_parent_reconciliation.group_ei_recon_user']
if not env['res.users'].search([('login', '=', 'demo.trainer')]):
    env['res.users'].with_context(no_reset_password=True).create({
        'name': 'DEMO Trainer', 'login': 'demo.trainer', 'password': 'demo', 'email': 'demo.trainer@example.invalid',
        'company_id': co.id, 'company_ids': [Command.set([co.id])], 'tz': 'Asia/Karachi',
        'group_ids': [Command.set([env.ref(g).id for g in TRAINER_GROUPS])], 'action_id': env.ref('ei_ui_theme.action_ei_home').id})
env.cr.commit()
print('DEMO feeding ready: codes D.01/D.02, parties, DA-DEMO-FEED-1')
