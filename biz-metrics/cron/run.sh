#!/usr/bin/env bash
# Cron wrapper for the biz-metrics rollup (installed as /data/biz-metrics/run.sh).
# Sources the node-only env file (mode 600), then runs runner/rollup.py.
# No secrets here. Phase 1 = collect-only (no alert logic).
set -euo pipefail

BASE_DIR="${BIZ_METRICS_HOME:-/data/biz-metrics}"
ENV_FILE="${BIZ_METRICS_ENV_FILE:-$BASE_DIR/env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

exec python3 "$BASE_DIR/runner/rollup.py" "$@"
