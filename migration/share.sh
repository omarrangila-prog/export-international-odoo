#!/bin/bash
# Share the staging copy on a temporary public web address (a Cloudflare quick tunnel) so other people can open it in their own browser.
#   migration/share.sh start [db]     prints the address; works only while this computer is on and this is running
#   migration/share.sh stop           closes the address and puts the server back on this computer only
#
# What it does for safety (a public address is a different thing from localhost):
#  * the two system-administrator logins (admin, demo.sysadmin) get random passwords nobody is told, because a system administrator can run code
#    on this computer; the new admin password is written to ~/.config/ei-provision/staging_admin.txt (readable by you only)
#  * the server runs without a database list or database manager page, and trusts the tunnel's forwarded address
#  * PIN sign-in is switched off while it is shared (the sign-in page shows no PIN tab): through a tunnel every visitor looks like this computer, so a
#    network rule cannot tell them apart. `share.sh stop` switches it back on. Visitors sign in with a user name and password
# The demo logins demo.<role> / demo stay as they are: anyone with the address can use them. It is the client's real code list on screen: give the address
# only to the people meant to see it, and stop it when the demo is over.
set -euo pipefail
cd "$(dirname "$0")/.."
. migration/env.sh
DB=${2:-ei20b}; PORT=${EI_PORT:-8369}
PIDF=~/.ei_tunnel.pid; URLF=~/.ei_tunnel.url; LOGF=/tmp/ei_tunnel.log
stop_server() { [ -f ~/.ei_server_$PORT.pid ] && kill "$(cat ~/.ei_server_$PORT.pid)" 2>/dev/null || true; sleep 3; }
case "${1:-}" in
start)
  [ -f "$PIDF" ] && kill -0 "$(cat $PIDF)" 2>/dev/null && { echo "already shared: $(cat $URLF)"; exit 0; }
  stop_server
  mkdir -p ~/.config/ei-provision; chmod 700 ~/.config/ei-provision
  ADMINPW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
  ei_shell -d "$DB" --log-level=error <<PY >/dev/null
env = env(su=True)
for login in ('admin', 'demo.sysadmin'):
    u = env['res.users'].search([('login', '=', login)])
    if u:
        u.password = '$ADMINPW' if login == 'admin' else '$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')'
env['ir.config_parameter'].set_bool('ei.pin.enabled', False)
env.cr.commit()
PY
  umask 077; printf 'admin password for the staging copy (set %s): %s\n' "$(date -Is)" "$ADMINPW" > ~/.config/ei-provision/staging_admin.txt
  EI_PUBLIC=1 EI_REPAIR_ASSETS=1 migration/serve.sh "$DB" | tail -1
  URL=""
  for attempt in 1 2 3; do                       # the first request for an address sometimes times out on this network: ask again
    nohup cloudflared tunnel --no-autoupdate --edge-ip-version 4 --url "http://127.0.0.1:$PORT" > "$LOGF" 2>&1 &
    echo $! > "$PIDF"
    for i in $(seq 1 20); do
      URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOGF" | grep -v '^https://api\.' | head -1 || true)
      [ -n "$URL" ] && break
      grep -q "failed to request" "$LOGF" && break
      sleep 3
    done
    [ -n "$URL" ] && break
    kill "$(cat $PIDF)" 2>/dev/null || true; sleep 2
  done
  [ -n "$URL" ] || { echo "no address yet; see $LOGF"; rm -f "$PIDF"; exit 1; }
  echo "$URL" > "$URLF"; echo "shared at: $URL"
  ;;
stop)
  [ -f "$PIDF" ] && kill "$(cat $PIDF)" 2>/dev/null || true; rm -f "$PIDF" "$URLF"
  stop_server
  ei_shell -d "$DB" --log-level=error <<<"env['ir.config_parameter'].sudo().set_bool('ei.pin.enabled', True); env.cr.commit()" >/dev/null || true
  migration/serve.sh "$DB" | tail -1
  echo "closed: the address no longer works; the server is on this computer only again and PIN sign-in is back on"
  ;;
*) echo "usage: migration/share.sh start|stop [db]"; exit 2;;
esac
