#!/bin/bash
# Looks at the shared demo every minute; if the server does not answer three times in a row it is restarted. usage: watch_fg.sh [port]
# The public address is checked too: if it is dead three times in a row while the server answers, the tunnel is restarted (the address
# then CHANGES: see migration/share.sh status).
PORT=${1:-8381}; BAD=0; PUB=0; URLF=$HOME/.ei_tunnel.url
while true; do
  if curl -s -m 25 -o /dev/null -f "http://127.0.0.1:$PORT/web/login"; then BAD=0
    U=$( [ -f "$URLF" ] && cat "$URLF" )
    if [ -z "$U" ] || curl -s -4 -m 25 -o /dev/null -f "$U/web/login"; then PUB=0
    elif curl -s -m 10 -o /dev/null https://www.cloudflare.com; then   # only blame the tunnel when this laptop is online
      PUB=$((PUB + 1)); echo "$(date -Is) public address did not answer ($PUB)" >> "$HOME/.ei_watch.log"
      if [ "$PUB" -ge 3 ]; then echo "$(date -Is) restarting the tunnel" >> "$HOME/.ei_watch.log"; systemctl --user restart ei-tunnel.service; PUB=0; sleep 60; fi
    fi
  else
    BAD=$((BAD + 1)); echo "$(date -Is) server did not answer ($BAD)" >> "$HOME/.ei_watch.log"
    if [ "$BAD" -ge 3 ]; then echo "$(date -Is) restarting the server" >> "$HOME/.ei_watch.log"; systemctl --user restart ei-odoo.service; BAD=0; fi
  fi
  sleep 60
done
