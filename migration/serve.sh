#!/bin/bash
# Start the staging server on 127.0.0.1:PORT only (never exposed on the network).
# usage: migration/serve.sh [db] [extra odoo args]     env: EI_PORT (default 8369), EI_REPAIR_ASSETS=1, EI_PUBLIC=1
# EI_PUBLIC=1 is for sharing it through a tunnel (migration/share.sh): the server then trusts the tunnel's forwarded address (so the PIN network
# rule sees the real visitor), and offers no database list / database manager page. It still listens on 127.0.0.1 only.
# Stop with: kill $(cat ~/.ei_server_$PORT.pid)       (never pkill -f: it can kill your own shell)
. "$(dirname "$0")/env.sh"
DB=${1:-ei20b}; shift
PORT=${EI_PORT:-8369}
ei_check_filestore "$DB" ${EI_REPAIR_ASSETS:+--repair-assets} || { echo "refusing to start: fix the filestore first (exit $?)"; exit 1; }
# an older server still holding the port would answer the check below and the new code would never load (27 Oct 2026): refuse instead
if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then echo "port $PORT is already in use (pid $(ss -ltnp "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)): stop that server first"; exit 1; fi
LOG=${EI_LOG:-/tmp/ei_server_$PORT.log}
PUBLIC_ARGS=(); [ -n "${EI_PUBLIC:-}" ] && PUBLIC_ARGS=(--proxy-mode --no-database-list "--db-filter=^$DB\$")
nohup "${EI_ODOO_CMD[@]}" -d "$DB" --http-interface=127.0.0.1 --http-port="$PORT" --workers=0 "${PUBLIC_ARGS[@]}" "$@" > "$LOG" 2>&1 &
echo $! > ~/.ei_server_$PORT.pid
[ "$PORT" = 8369 ] && ln -sf ~/.ei_server_8369.pid ~/.ei_server.pid
for i in $(seq 1 90); do kill -0 "$(cat ~/.ei_server_$PORT.pid)" 2>/dev/null || { echo "server stopped while starting; see $LOG"; exit 1; }
  curl -s -o /dev/null localhost:$PORT/web/login && { echo "up: http://localhost:$PORT (db $DB, pid $(cat ~/.ei_server_$PORT.pid), data dir $EI_DATA_DIR)"; exit 0; }; sleep 2; done
echo "server did not come up; see $LOG"; exit 1
