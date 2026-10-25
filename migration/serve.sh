#!/bin/bash
# Start the staging server on 127.0.0.1:8369 only (never exposed on the network). usage: migration/serve.sh [db] [extra odoo args]
# Stop with: kill $(cat ~/.ei_server.pid)
cd "$(dirname "$0")/.."
DB=${1:-ei20b}; shift
R=$HOME/odoo20/root/usr/lib/python3/dist-packages
LOG=${EI_LOG:-/tmp/ei_server.log}
nohup $HOME/odoo20/odoo20 -c /dev/null -d "$DB" --addons-path=$R/odoo/addons,$PWD/addons \
  --http-interface=127.0.0.1 --http-port=8369 --workers=0 "$@" > "$LOG" 2>&1 &
echo $! > ~/.ei_server.pid
for i in $(seq 1 60); do curl -s -o /dev/null localhost:8369/web/login && { echo "up: http://localhost:8369 (db $DB, pid $(cat ~/.ei_server.pid))"; exit 0; }; sleep 2; done
echo "server did not come up; see $LOG"; exit 1
