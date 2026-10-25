"""Make the (single) company a Pakistan / PKR company and load the Pakistan chart of accounts.
Run once on a NEW database, before any entry is posted:   odoo shell -d <db> ... < migration/setup_company.py"""
co = env.company
pk = env.ref('base.pk')
pkr = env.ref('base.PKR')
pkr.active = True
co.write({'name': 'Export International (staging)', 'country_id': pk.id, 'currency_id': pkr.id})
tmpl = env['account.chart.template']
try:
    tmpl.try_loading('pk', co, install_demo=False)
    print('chart loaded: pk')
except Exception as e:                      # keep the generic chart rather than fail the whole build
    print('chart not loaded:', str(e)[:120])
env.cr.commit()
print('company:', co.name, co.country_id.code, co.currency_id.name)
