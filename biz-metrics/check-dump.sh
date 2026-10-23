#!/usr/bin/env bash
# Verify the pg-shared dump job includes the biz_metrics DB (AC#1).
# Checks the node env file for PG_SHARED_DBS containing "biz_metrics".
# Prints only the verdict (never secrets). Run on contabo-b:
#   sudo ./biz-metrics/check-dump.sh [/etc/coolify-pg-dump.env]
set -euo pipefail
ENV_FILE="${1:-${COOLIFY_PGDUMP_ENV_FILE:-/etc/coolify-pg-dump.env}}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "MISSING: env file not found: $ENV_FILE"
  echo "hint: install the dump job first (machine-management/backups/install-coolify-pg-dump.sh)"
  exit 1
fi
DBS="$(grep -E '^[[:space:]]*PG_SHARED_DBS=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '\042\047')"
if [[ " $DBS " =~ [[:space:]]biz_metrics[[:space:]] ]]; then
  echo "OK: PG_SHARED_DBS lists biz_metrics"
else
  echo "MISSING: add biz_metrics to PG_SHARED_DBS in $ENV_FILE"
  echo 'hint: PG_SHARED_DBS="cmp aisl website biz_metrics"'
  exit 1
fi
