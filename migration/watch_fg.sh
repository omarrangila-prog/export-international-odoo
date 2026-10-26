#!/bin/bash
# Looks at the shared demo every minute; if the server does not answer three times in a row it is restarted. usage: watch_fg.sh [port]
PORT=${1:-8381}; BAD=0
while true; do
  if curl -s -m 25 -o /dev/null -f "http://127.0.0.1:$PORT/web/login"; then BAD=0
  else
    BAD=$((BAD + 1)); echo "$(date -Is) server did not answer ($BAD)" >> "$HOME/.ei_watch.log"
    if [ "$BAD" -ge 3 ]; then echo "$(date -Is) restarting the server" >> "$HOME/.ei_watch.log"; systemctl --user restart ei-odoo.service; BAD=0; fi
  fi
  sleep 60
done
