#!/bin/bash
# Quick test run of selected modules on a FRESH database. usage: tests/run_modules.sh "mod1,mod2" [db] [lines]
. "$(dirname "$0")/../migration/env.sh"
DB=${2:-ei_quick}
LOG=/tmp/ei_quick.log
ei_drop_db "$DB"; createdb "$DB"
ei_odoo -d "$DB" -i "$1" --test-enable --test-tags ei --stop-after-init --without-demo=all --http-port=8179 > "$LOG" 2>&1
echo "exit $?"; grep -E "tests in|failed.*tests" "$LOG" | tail -2
grep -E "CRITICAL|ERROR|FAIL:" "$LOG" | grep -v "bad query\|duplicate key\|^ERROR: dup" | sed 's/.*odoo.addons.//' | head -${3:-25}
ei_drop_db "$DB"
