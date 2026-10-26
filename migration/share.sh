#!/bin/bash
# Share a COPY of the staging system on a temporary public web address, and keep it running for days.
#   migration/share.sh start [--reset]   copy the code and data to ~/ei-demo / database ei_demo, make it safe, start it supervised, print the address
#   migration/share.sh status            the address, whether everything is running, how long
#   migration/share.sh stop              close the address and stop the copy (your own staging on port 8369 is never touched)
#
# Why a copy: the shared demo must not change under visitors' feet when the code in this folder is being worked on, and what visitors do (or
# the safety steps below) must not touch the staging you demonstrate yourself. The code is the last COMMITTED version; the data is a copy of
# database ei20b made at start (--reset makes a fresh copy, throwing away what visitors entered; without it a running demo's data is kept).
#
# Kept running by systemd (user): the server, the tunnel, a watcher that restarts a server that stops answering, and a lock that stops this
# laptop sleeping when idle. They come back after a restart of the laptop. The address of a quick tunnel is chosen by Cloudflare: it stays the
# same while the tunnel stays connected (it reconnects by itself after a network change) but is NEW if the tunnel process ever restarts: look at
# `share.sh status`. KEEP THE LID OPEN AND THE CHARGER IN: closing the lid suspends the laptop whatever a program asks (logind setting).
#
# Safety (a public address is a different thing from localhost):
#  * the two system-administrator logins (admin, demo.sysadmin) get random passwords nobody is told, because a system administrator can run code
#    on this computer; the admin password is written to ~/.config/ei-provision/demo_admin.txt (readable by you only)
#  * no database list or database manager page; the server trusts the tunnel's forwarded address
#  * PIN sign-in is off in the copy (through a tunnel every visitor looks like this computer, so a network rule cannot tell them apart)
# Visitors use demo.<role> / demo. It is the client's real code list on screen: give the address only to the people meant to see it.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEMO=$HOME/ei-demo; DB=ei_demo; PORT=8381; SRC_DB=ei20b
UNITS=$HOME/.config/systemd/user; URLF=$HOME/.ei_tunnel.url
DATA=${EI_DATA_DIR:-$HOME/.local/share/Odoo}
U=(ei-awake ei-odoo ei-tunnel ei-watch)

stop_units() {
  for u in "${U[@]}"; do systemctl --user disable --now "$u.service" 2>/dev/null || true; done
  [ -f ~/.ei_tunnel.pid ] && kill "$(cat ~/.ei_tunnel.pid)" 2>/dev/null || true; rm -f ~/.ei_tunnel.pid "$URLF"     # the earlier, unsupervised version
}
status() {
  echo "address : $( [ -f "$URLF" ] && cat "$URLF" || echo '(none: not shared)')"
  for u in "${U[@]}"; do printf '%-10s %s (since %s)\n' "$u" "$(systemctl --user is-active $u.service 2>/dev/null || true)" "$(systemctl --user show $u.service -p ActiveEnterTimestamp --value 2>/dev/null | cut -c1-30)"; done
  curl -s -m 20 -o /dev/null -w 'local server answers: %{http_code}\n' "http://127.0.0.1:$PORT/web/login" || echo 'local server answers: no'
  [ -f ~/.ei_watch.log ] && { echo '--- watcher log (last 3):'; tail -3 ~/.ei_watch.log; }
}

case "${1:-}" in
start)
  RESET=0; [ "${2:-}" = "--reset" ] && RESET=1
  git -C "$REPO" diff --quiet HEAD -- addons migration 2>/dev/null || echo "note: uncommitted changes are NOT in the shared copy (it uses the last commit)"
  stop_units
  # 1. the code: the last commit, in its own folder
  rm -rf "$DEMO.new"; mkdir -p "$DEMO.new"; git -C "$REPO" archive HEAD | tar -x -C "$DEMO.new"; rm -rf "$DEMO"; mv "$DEMO.new" "$DEMO"
  . "$DEMO/migration/env.sh"
  # 2. the data: a copy of the staging database (only if there is none yet, or --reset)
  if [ "$RESET" = 1 ] || ! psql -lqt | cut -d'|' -f1 | grep -qw "$DB"; then
    [ -f ~/.ei_server_8369.pid ] && kill "$(cat ~/.ei_server_8369.pid)" 2>/dev/null || true; sleep 3     # a template database cannot have other sessions on it
    dropdb --if-exists "$DB"; rm -rf "$DATA/filestore/$DB"
    createdb -T "$SRC_DB" "$DB"; cp -a "$DATA/filestore/$SRC_DB" "$DATA/filestore/$DB"
    ( cd "$REPO" && migration/serve.sh "$SRC_DB" | tail -1 )                                                   # your own staging comes back
    PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
    ei_shell -d "$DB" --log-level=error <<PY >/dev/null
env = env(su=True)
for login in ('admin', 'demo.sysadmin'):
    u = env['res.users'].search([('login', '=', login)])
    if u:
        u.password = '$PW' if login == 'admin' else '$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')'
env['ir.config_parameter'].set_bool('ei.pin.enabled', False)
env['ir.config_parameter'].set_str('ei.environment_label', 'DEMO - synthetic data and a copy of the client code list')
env.cr.commit()
PY
    mkdir -p ~/.config/ei-provision; chmod 700 ~/.config/ei-provision
    ( umask 077; printf 'admin password of the shared demo database %s (set %s): %s\n' "$DB" "$(date -Is)" "$PW" > ~/.config/ei-provision/demo_admin.txt )
  fi
  # 3. bring the copy's modules up to the copied code
  ei_odoo -d "$DB" -u "$EI_MODULES" --stop-after-init --http-port=8283 > /tmp/ei_demo_update.log 2>&1 || { echo "module update failed; see /tmp/ei_demo_update.log"; exit 1; }
  # 4. supervised services
  mkdir -p "$UNITS"
  unit() { # name, description, after, command
    cat > "$UNITS/$1.service" <<UNIT
[Unit]
Description=$2
${3:+After=$3}

[Service]
ExecStart=$4
Restart=always
RestartSec=8

[Install]
WantedBy=default.target
UNIT
  }
  unit ei-awake  "Export International demo: keep the laptop awake" "" "/usr/bin/systemd-inhibit --what=sleep:idle --who=ExportInternationalDemo --why=SharedDemo --mode=block /usr/bin/sleep infinity"
  unit ei-odoo   "Export International demo: server" "" "$DEMO/migration/serve_fg.sh $DB $PORT"
  unit ei-tunnel "Export International demo: public address" "ei-odoo.service" "$DEMO/migration/tunnel_fg.sh $PORT"
  unit ei-watch  "Export International demo: watcher" "ei-odoo.service" "$DEMO/migration/watch_fg.sh $PORT"
  systemctl --user daemon-reload
  for u in "${U[@]}"; do systemctl --user enable --now "$u.service" >/dev/null 2>&1; done
  for i in $(seq 1 90); do [ -f "$URLF" ] && break; sleep 3; done
  [ -f "$URLF" ] || { echo "no address yet; see /tmp/ei_tunnel.log and: journalctl --user -u ei-tunnel"; exit 1; }
  echo "shared at: $(cat $URLF)"
  echo "(it keeps running by itself; check it any time with: migration/share.sh status)"
  ;;
status) status;;
stop)
  stop_units; rm -f "$UNITS"/ei-{awake,odoo,tunnel,watch}.service; systemctl --user daemon-reload
  echo "closed: the address no longer works and the shared copy is stopped (database $DB is kept; your staging on 8369 was not touched)"
  ;;
*) echo "usage: migration/share.sh start [--reset] | status | stop"; exit 2;;
esac
