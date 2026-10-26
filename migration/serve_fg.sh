#!/bin/bash
# The shared demo's server, in the foreground (systemd starts it and starts it again if it ever stops). Used by share.sh; not for daily use.
# usage: serve_fg.sh [db] [port]
. "$(dirname "$0")/env.sh"
DB=${1:-ei_demo}; PORT=${2:-8381}
ei_check_filestore "$DB" --repair-assets || exit 1
exec "${EI_ODOO_CMD[@]}" -d "$DB" --http-interface=127.0.0.1 --http-port="$PORT" --workers=0 --proxy-mode --no-database-list "--db-filter=^$DB\$" --limit-time-real=600
