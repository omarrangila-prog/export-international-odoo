#!/bin/bash
# Shared settings for every Export International script. SOURCE it:  . "$(dirname "$0")/../migration/env.sh"
#
# ONE persistent data directory for the Odoo filestore. Never point it at a temp or scratch folder: generated web
# bundles and uploaded files live there while the database keeps rows that point at them. (25 Oct 2026: a staging
# server started with --data-dir in a throw-away scratch folder, the folder was wiped, and every web bundle went
# missing -> blank page. The rows survived, the files did not.)
EI_REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export EI_DATA_DIR=${EI_DATA_DIR:-$HOME/.local/share/Odoo}
EI_R=$HOME/odoo20/root/usr/lib/python3/dist-packages
EI_ADDONS=$EI_R/odoo/addons,$EI_REPO/addons

# PDF engine for Daily Order / invoice / dashboard PDFs. Odoo needs `wkhtmltopdf` (patched Qt) on PATH; on this machine it is
# unpacked from the official wkhtmltopdf 0.12.6.1-3 package into ~/odoo20/wkhtml (see docs/deployment_runbook.md).
[ -d "$HOME/odoo20/wkhtml/usr/local/bin" ] && export PATH="$HOME/odoo20/wkhtml/usr/local/bin:$PATH"

# every Export International module, in install order (one list for build, tests and CI)
EI_MODULES=ei_legacy_master,ei_bank_operations,ei_cashbook,ei_contract_da,ei_daily_orders,ei_material_lifting,ei_invoice_extensions,ei_parent_reconciliation,ei_trade_lc,ei_management_dashboard,ei_ui_theme,ei_party360

# run Odoo 20 with our addons and the persistent data dir:  ei_odoo -d DB -i module ...
EI_ODOO_CMD=("$HOME/odoo20/odoo20" -c /dev/null --addons-path="$EI_ADDONS" --data-dir "$EI_DATA_DIR")
ei_odoo() { "${EI_ODOO_CMD[@]}" "$@"; }
# odoo shell takes the subcommand FIRST:  ei_shell -d DB < script.py
ei_shell() { "$HOME/odoo20/odoo20" shell -c /dev/null --addons-path="$EI_ADDONS" --data-dir "$EI_DATA_DIR" --no-http "$@"; }

# drop a database AND its filestore (a re-created database must not inherit a stale filestore)
ei_drop_db() { dropdb --if-exists "${1:?db name}"; rm -rf "${EI_DATA_DIR:?}/filestore/${1:?}"; }

# fail loudly when the database points at files that are not on disk (see migration/check_filestore.py)
ei_check_filestore() { python3 "$EI_REPO/migration/check_filestore.py" "$@"; }
