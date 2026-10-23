#!/usr/bin/env bash
# Root cron wrapper; secrets remain in the existing /etc secrets directory.
# DB access uses biz_ro (sources) and biz_rw (aggregate store) only.
set -euo pipefail
BASE_DIR="${BIZ_METRICS_HOME:-/data/biz-metrics}"
ENV_FILE="${BIZ_METRICS_ENV_FILE:-/etc/biz-metrics.env}"
exec 9>"$BASE_DIR/run.lock"
flock -n 9 || { echo "rollup already running"; exit 1; }
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a
for stack in SHARED RELAY; do
  container_var="BIZ_METRICS_${stack}_CONTAINER"
  if [[ -n "${!container_var:-}" ]]; then
    address="$(docker inspect --format '{{with index .NetworkSettings.Networks "coolify"}}{{.IPAddress}}{{end}}' "${!container_var}")"
    [[ -n "$address" ]] || { echo "missing $stack database network address"; exit 1; }
    export "BIZ_METRICS_${stack}_HOSTADDR=$address"
  fi
done
exec "$BASE_DIR/venv/bin/python" "$BASE_DIR/runner/rollup.py" "$@"
