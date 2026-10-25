#!/bin/bash
# Quick test run of selected modules on a FRESH database. usage: tests/run_modules.sh "mod1,mod2" [db]
cd "$(dirname "$0")/.."
DB=${2:-ei_quick}
R=$HOME/odoo20/root/usr/lib/python3/dist-packages
LOG=/tmp/ei_quick.log
dropdb --if-exists "$DB"; createdb "$DB"
$HOME/odoo20/odoo20 -c /dev/null -d "$DB" --addons-path=$R/odoo/addons,$PWD/addons -i "$1" --test-enable --test-tags ei \
  --stop-after-init --without-demo=all --http-port=8179 > "$LOG" 2>&1
echo "exit $?"; grep -E "tests in|failed.*tests" "$LOG" | tail -2
grep -E "CRITICAL|ERROR|FAIL:" "$LOG" | sed 's/.*odoo.addons.//' | head -${3:-25}
