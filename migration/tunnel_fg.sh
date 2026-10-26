#!/bin/bash
# The shared demo's public address (a Cloudflare quick tunnel), in the foreground. systemd starts it again if it stops (the address then changes:
# `share.sh status` shows the current one). usage: tunnel_fg.sh [port]
PORT=${1:-8381}
LOG=/tmp/ei_tunnel.log; URLF=$HOME/.ei_tunnel.url
: > "$LOG"; rm -f "$URLF"
cloudflared tunnel --no-autoupdate --edge-ip-version 4 --url "http://127.0.0.1:$PORT" > "$LOG" 2>&1 &
CF=$!
trap 'kill $CF 2>/dev/null' TERM INT EXIT
URL=""
for i in $(seq 1 40); do                                   # the first request for an address sometimes times out on this network: give up and let systemd ask again
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | grep -v '^https://api\.' | head -1 || true)
  [ -n "$URL" ] && break
  kill -0 $CF 2>/dev/null || exit 1
  sleep 3
done
[ -n "$URL" ] || exit 1
echo "$URL" > "$URLF"
wait $CF
