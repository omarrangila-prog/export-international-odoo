#!/bin/bash
# Real-browser end-to-end run on a FRESH copy of a pristine staging database. Part of the standard test process.
#   tests/run_e2e.sh [--spec NAME]            env: EI_E2E_REBUILD=1 rebuilds the pristine template (minutes)
# The template (ei_e2e_tpl) is built once by migration/build_staging.sh and cloned for every run, so each run
# starts from identical data in seconds; the clone is updated to the current code before the browser starts.
cd "$(dirname "$0")/.."
. migration/env.sh
TPL=${EI_E2E_TPL:-ei_e2e_tpl}; DB=${EI_E2E_DB:-ei_e2e}; PORT=${EI_E2E_PORT:-8372}
export NODE_PATH=${NODE_PATH:-$HOME/tfmsg-website/node_modules}
# rebuild the template when asked, when missing, or when module code changed since it was built
STAMP=$EI_DATA_DIR/.${TPL}.built
if [ -n "$EI_E2E_REBUILD" ] || ! psql -lqt | cut -d'|' -f1 | grep -qw "$TPL" || [ ! -f "$STAMP" ] || \
   [ -n "$(find addons -name '__manifest__.py' -newer "$STAMP" -print -quit)" ]; then
  echo "building pristine template $TPL (a few minutes)..."
  migration/build_staging.sh "$TPL" > /tmp/ei_build_tpl.out 2>&1 || { tail -5 /tmp/ei_build_tpl.out; exit 2; }
  touch "$STAMP"
fi
ei_drop_db "$DB"; createdb -T "$TPL" "$DB"
cp -r "$EI_DATA_DIR/filestore/$TPL" "$EI_DATA_DIR/filestore/$DB" 2>/dev/null
ei_odoo -d "$DB" -i "$EI_MODULES" -u "$EI_MODULES" --stop-after-init --http-port=8279 > /tmp/ei_e2e_update.log 2>&1 || { tail -5 /tmp/ei_e2e_update.log; exit 2; }
ei_check_filestore "$DB" --repair-assets >/dev/null
EI_PORT=$PORT migration/serve.sh "$DB" | tail -1 || exit 2
rm -f docs/ui/e2e/FAIL_*.png   # screenshots of earlier failures must not look like current ones
node tests/e2e/run.js --base "http://127.0.0.1:$PORT" --out docs/ui/e2e --md docs/e2e_results.md "$@"
code=$?
kill "$(cat ~/.ei_server_$PORT.pid)" 2>/dev/null
exit $code
