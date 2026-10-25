#!/bin/bash
# Rebuild a complete STAGING site on Odoo 20 from nothing: db, modules, PKR company, 639 codes, roles, DEMO data.
# usage: migration/build_staging.sh [dbname]        (needs ~/odoo20, see docs/deployment_runbook.md)
set -e
cd "$(dirname "$0")/.."
DB=${1:-ei20}
R=$HOME/odoo20/root/usr/lib/python3/dist-packages
AP=$R/odoo/addons,$PWD/addons
O="$HOME/odoo20/odoo20 -c /dev/null -d $DB --addons-path=$AP"
dropdb --if-exists $DB; createdb $DB
$O -i ei_legacy_master,ei_bank_operations,ei_cashbook,ei_contract_da,ei_daily_orders,ei_material_lifting,ei_invoice_extensions,ei_parent_reconciliation,ei_trade_lc,ei_management_dashboard,ei_ui_theme,l10n_pk --stop-after-init --without-demo=all --http-port=8279 > /tmp/ei_build.log 2>&1
$HOME/odoo20/odoo20 shell -c /dev/null -d $DB --addons-path=$AP --log-level=error < migration/setup_company.py
EXI_SOURCE=migration/source/CODE_LIST.xlsx $HOME/odoo20/odoo20 shell -c /dev/null -d $DB --addons-path=$AP --log-level=error < migration/import_legacy_codes.py | grep BATCH
EI_USER=admin $HOME/odoo20/odoo20 shell -c /dev/null -d $DB --addons-path=$AP --log-level=error < migration/grant_uat_roles.py | grep granted
$HOME/odoo20/odoo20 shell -c /dev/null -d $DB --addons-path=$AP --log-level=error < migration/seed_uat_demo.py | grep "DEMO data"
echo "staging ready: db=$DB  admin/admin + demo.<role>/demo"
