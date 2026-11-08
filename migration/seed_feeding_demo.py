"""DEMO data for the DA feeding desk. Run on a STAGING database only, after seed_uat_demo.py:
    odoo shell -d <db> ... < migration/seed_feeding_demo.py

- two DEMO customer codes (D.01, D.02) in a DEMO batch, verified by the demo mapping approver and linked to the demo customers,
  so a fed coil can go all the way to approval on staging (the client's real codes stay unverified, as they are);
- a DEMO exchange rate for USD and a DEMO USD contract (direct rates), so a USD DA can be fed and approved;
- one approved DEMO DA fed through the desk with three coils (normal sale, purchase with CN, loss sale), so the feeding
  history and the credit note register have rows to show.
Every name starts with DEMO. Nothing here is client data, and the USD rate is a round demo figure, not a market rate."""
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

# ---- DEMO USD rate and USD contract
usd = env.ref('base.USD')
usd.active = True
if not env['res.currency.rate'].search([('currency_id', '=', usd.id), ('company_id', '=', co.id)]):
    env['res.currency.rate'].create({'currency_id': usd.id, 'company_id': co.id, 'name': today.replace(day=1),
                                     'rate': 1 / 280.0})            # DEMO: 1 USD = 280 PKR from the 1st of this month
if not env['ei.contract'].search([('contract_ref', '=', 'DEMO/IMP/USD-1')]):
    ct = env['ei.contract'].with_user(U['contracts']).create({
        'parent_partner_id': parent.id, 'contract_ref': 'DEMO/IMP/USD-1', 'contract_type': 'local_direct', 'currency_id': usd.id,
        'line_ids': [Command.create({'product_id': prod.id, 'grade': 'Imported CR 0.5 mm (USD)', 'ordered_mtl': 100,
                                     'purchase_rate': 800, 'sale_rate': 812})]})
    att(ct); ct.with_user(U['contracts']).action_review(); ct.with_user(U['contractapprover']).action_approve()
    ct.with_user(U['contracts']).action_activate()

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
env.cr.commit()
print('DEMO feeding ready: codes D.01/D.02, USD contract, DA-DEMO-FEED-1')
