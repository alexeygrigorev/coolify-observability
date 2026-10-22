#!/usr/bin/env bash
# Daily Contabo obs archive: closed day (day-before-yesterday, Europe/Berlin)
# → gzip → S3 (coolify/obs/{metrics,logs}/YYYY/MM/DD/) → verify → rely on
# VM/VL -retentionPeriod=2d for local drop (plus optional VL partition rm).
#
# Runs ON contabo-a (.163) via /etc/cron.d/coolify-obs-archive.
# Secrets: /etc/coolify-obs-archive.env (root 600) — never in git.
#
# Exit 0 only if both metrics and logs objects are uploaded and verified
# (or SKIP when the day has no local data yet — first 48h after install).
set -euo pipefail

ENV_FILE="${COOLIFY_OBS_ARCHIVE_ENV_FILE:-/etc/coolify-obs-archive.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

log() { printf '%s %s\n' "$(TZ=Europe/Berlin date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

WORKDIR="${WORKDIR:-/var/tmp/coolify-obs-archive}"
LOCK_FILE="${LOCK_FILE:-/var/lock/coolify-obs-archive.lock}"
VM_URL="${VM_URL:-http://127.0.0.1:8428}"
VL_URL="${VL_URL:-http://127.0.0.1:9428}"
VL_DATA="${VL_DATA:-/data/obs/vl}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-coolify/obs}"
S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-west-1}"
DROP_VL_PARTITION="${DROP_VL_PARTITION:-0}"
# TARGET_DAY=YYYY-MM-DD overrides day-before-yesterday (smoke / backfill)
TARGET_DAY="${TARGET_DAY:-}"

[[ -n "$S3_BUCKET" ]] || fail "S3_BUCKET is not set (see coolify-obs-archive.env.example)"

for bin in curl gzip aws flock jq date; do
  command -v "$bin" >/dev/null 2>&1 || fail "missing required binary: $bin"
done

if [[ -z "$TARGET_DAY" ]]; then
  TARGET_DAY="$(TZ=Europe/Berlin date -d '2 days ago' '+%Y-%m-%d')"
fi
# Berlin calendar-day bounds → UTC RFC3339 (avoid "00:00:00 +1 day" — GNU date
# parses "+1" as a timezone). Use epoch round-trip.
START_EPOCH="$(TZ=Europe/Berlin date -d "${TARGET_DAY} 00:00:00" '+%s')"
END_EPOCH="$(TZ=Europe/Berlin date -d "${TARGET_DAY} + 1 day" '+%s')"
START_UTC="$(date -u -d "@${START_EPOCH}" '+%Y-%m-%dT%H:%M:%SZ')"
END_UTC="$(date -u -d "@${END_EPOCH}" '+%Y-%m-%dT%H:%M:%SZ')"
DAY_PATH="$(TZ=Europe/Berlin date -d "${TARGET_DAY}" '+%Y/%m/%d')"
STAMP="$(TZ=Europe/Berlin date '+%Y%m%dT%H%M%z')"
# VL on-disk partitions are UTC YYYYMMDD; Berlin day can span 1–2 UTC days
UTC_DAY_START="$(date -u -d "@${START_EPOCH}" '+%Y%m%d')"
UTC_DAY_END="$(date -u -d "@$((END_EPOCH - 1))" '+%Y%m%d')"

mkdir -p "$WORKDIR"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another archive run is in progress (lock: $LOCK_FILE)"

log "start target_day=${TARGET_DAY} berlin day_path=${DAY_PATH} start_utc=${START_UTC} end_utc=${END_UTC}"

s3_uri() { printf 's3://%s/%s' "$S3_BUCKET" "$1"; }
s3_cp() {
  local src="$1" key="$2"
  if [[ -n "$S3_ENDPOINT_URL" ]]; then
    aws s3 cp "$src" "$(s3_uri "$key")" --endpoint-url "$S3_ENDPOINT_URL" --only-show-errors
  else
    aws s3 cp "$src" "$(s3_uri "$key")" --only-show-errors
  fi
}
s3_head() {
  local key="$1"
  if [[ -n "$S3_ENDPOINT_URL" ]]; then
    aws s3api head-object --bucket "$S3_BUCKET" --key "$key" --endpoint-url "$S3_ENDPOINT_URL" >/dev/null
  else
    aws s3api head-object --bucket "$S3_BUCKET" --key "$key" >/dev/null
  fi
}

METRICS_RAW="${WORKDIR}/metrics-${TARGET_DAY}.ndjson"
METRICS_GZ="${METRICS_RAW}.gz"
LOGS_RAW="${WORKDIR}/logs-${TARGET_DAY}.ndjson"
LOGS_GZ="${LOGS_RAW}.gz"
rm -f "$METRICS_RAW" "$METRICS_GZ" "$LOGS_RAW" "$LOGS_GZ"

# --- metrics: VictoriaMetrics /api/v1/export ---
log "export metrics from ${VM_URL}"
curl -fsS -G "${VM_URL}/api/v1/export" \
  --data-urlencode 'match[]={__name__!=""}' \
  --data-urlencode "start=${START_UTC}" \
  --data-urlencode "end=${END_UTC}" \
  -o "$METRICS_RAW" \
  || fail "VM export failed"

METRICS_BYTES="$(wc -c <"$METRICS_RAW" | tr -d ' ')"
if [[ "$METRICS_BYTES" -eq 0 ]]; then
  log "WARN: metrics export empty for ${TARGET_DAY} (OK if stack <48h old)"
  printf '{"status":"empty","day":"%s","kind":"metrics"}\n' "$TARGET_DAY" >"$METRICS_RAW"
fi
gzip -c "$METRICS_RAW" >"$METRICS_GZ"
METRICS_KEY="${S3_PREFIX}/metrics/${DAY_PATH}/metrics-${TARGET_DAY}-${STAMP}.ndjson.gz"
log "upload metrics key=${METRICS_KEY} bytes_gz=$(wc -c <"$METRICS_GZ" | tr -d ' ')"
s3_cp "$METRICS_GZ" "$METRICS_KEY"
s3_head "$METRICS_KEY" || fail "S3 head-object failed for metrics ${METRICS_KEY}"
log "verified metrics $(s3_uri "$METRICS_KEY")"

# --- logs: VictoriaLogs LogsQL stream ---
log "export logs from ${VL_URL}"
# limit=0 means no artificial row cap on recent VL; older builds ignore unknown args
curl -fsS "${VL_URL}/select/logsql/query" \
  --data-urlencode "query=_time:[${START_UTC},${END_UTC})" \
  -o "$LOGS_RAW" \
  || fail "VL logsql export failed"

LOGS_BYTES="$(wc -c <"$LOGS_RAW" | tr -d ' ')"
if [[ "$LOGS_BYTES" -eq 0 ]]; then
  log "WARN: logs export empty for ${TARGET_DAY} (OK if stack <48h old)"
  printf '{"status":"empty","day":"%s","kind":"logs"}\n' "$TARGET_DAY" >"$LOGS_RAW"
fi
gzip -c "$LOGS_RAW" >"$LOGS_GZ"
LOGS_KEY="${S3_PREFIX}/logs/${DAY_PATH}/logs-${TARGET_DAY}-${STAMP}.ndjson.gz"
log "upload logs key=${LOGS_KEY} bytes_gz=$(wc -c <"$LOGS_GZ" | tr -d ' ')"
s3_cp "$LOGS_GZ" "$LOGS_KEY"
s3_head "$LOGS_KEY" || fail "S3 head-object failed for logs ${LOGS_KEY}"
log "verified logs $(s3_uri "$LOGS_KEY")"

# --- optional: drop closed VL UTC partitions fully older than retention window ---
# Only remove partitions whose UTC day is strictly before yesterday UTC, and only
# after S3 verify. Active today/yesterday partitions are never touched.
if [[ "$DROP_VL_PARTITION" == "1" ]]; then
  YDAY_UTC="$(TZ=UTC date -d '1 day ago' '+%Y%m%d')"
  for part in "$UTC_DAY_START" "$UTC_DAY_END"; do
    [[ -n "$part" ]] || continue
    # never drop today or yesterday (UTC)
    if [[ "$part" -ge "$YDAY_UTC" ]]; then
      log "skip VL partition drop ${part} (still within yesterday/today UTC)"
      continue
    fi
    PART_DIR="${VL_DATA}/partitions/${part}"
    if [[ -d "$PART_DIR" ]]; then
      log "drop local VL partition ${PART_DIR} (archived day ${TARGET_DAY})"
      rm -rf "$PART_DIR"
    else
      log "VL partition ${PART_DIR} already absent"
    fi
  done
fi

rm -f "$METRICS_RAW" "$METRICS_GZ" "$LOGS_RAW" "$LOGS_GZ"
log "ALL_DONE day=${TARGET_DAY} metrics=${METRICS_KEY} logs=${LOGS_KEY}"
