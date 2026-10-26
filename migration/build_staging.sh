#!/bin/bash
# Rebuild a complete STAGING site on Odoo 20 from nothing: db, modules, PKR company, 639 codes, roles, DEMO data.
# usage: migration/build_staging.sh [dbname]        (needs ~/odoo20, see docs/deployment_runbook.md)
set -e
cd "$(dirname "$0")/.."
. migration/env.sh
DB=${1:-ei20}
ei_drop_db $DB; createdb $DB
ei_odoo -d $DB -i $EI_MODULES,l10n_pk --stop-after-init --without-demo=all --http-port=8279 > /tmp/ei_build.log 2>&1
ei_shell -d $DB --log-level=error < migration/setup_company.py
EXI_SOURCE=migration/source/CODE_LIST.xlsx ei_shell -d $DB --log-level=error < migration/import_legacy_codes.py | grep BATCH
EI_USER=admin ei_shell -d $DB --log-level=error < migration/grant_uat_roles.py | grep granted
ei_shell -d $DB --log-level=error < migration/seed_uat_demo.py | grep "DEMO data"
ei_shell -d $DB --log-level=error < migration/seed_dashboard_history.py | grep "DEMO history"
ei_check_filestore $DB
echo "staging ready: db=$DB  admin/admin + demo.<role>/demo   (serve: migration/serve.sh $DB)"
