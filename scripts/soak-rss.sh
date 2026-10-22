#!/usr/bin/env bash
# Sample OpenObserve + Vector RSS on contabo-a. Gate: 512–1024 MiB for OO.
set -euo pipefail
echo "ts_europe_berlin=$(TZ=Europe/Berlin date -Iseconds)"
for c in openobserve vector-contabo-a; do
  id=$(sudo docker ps -q -f name=^/${c}$ || true)
  if [[ -z "$id" ]]; then echo "$c not_running"; continue; fi
  rss=$(ps -o rss= -p "$(sudo docker inspect -f '{{.State.Pid}}' "$id")" 2>/dev/null | awk '{print $1}')
  echo "$c rss_kib=${rss:-unknown}"
done
free -h | head -2
