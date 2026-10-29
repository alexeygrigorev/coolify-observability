#!/usr/bin/env bash
# Daily Contabo obs archive: closed day (day-before-yesterday, Europe/Berlin)
# → gzip → S3 (coolify/obs/{metrics,logs}/YYYY/MM/DD/) → verify. Local drop is
# VM/VL -retentionPeriod (VL 14d since bfd84d52, so a failed day can be retried).
#
# Runs ON contabo-a (.163) via /etc/cron.d/coolify-obs-archive.
# Secrets: /etc/coolify-obs-archive.env (root 600) — never in git.
#
# Logs are exported in bounded windows (VL_WINDOW_SECONDS, default 1h), one at
# a time: a single full-day /select/logsql/query exceeds VL's
# -search.maxQueryDuration and is cut mid-stream (curl 56, bfd84d52). Each
# window is retried and only accepted when its row count matches a
# `stats count()` of the same window and the last line is complete JSON.
# Partial output is never uploaded as an archive.
#
# Exit 0 only if every requested kind is uploaded and head-verified. Any other
# exit fires ObsArchiveFailed in Alertmanager in the same run; success resolves it.
set -euo pipefail

ENV_FILE="${COOLIFY_OBS_ARCHIVE_ENV_FILE:-/etc/coolify-obs-archive.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

log() { printf '%s %s\n' "$(TZ=Europe/Berlin date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }
FAIL_REASON=""
fail() { FAIL_REASON="$*"; log "ERROR: $*"; exit 1; }

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
# KINDS="logs" re-archives only logs (backfill when metrics already landed)
KINDS="${KINDS:-metrics logs}"
VL_WINDOW_SECONDS="${VL_WINDOW_SECONDS:-3600}"
RETRIES="${RETRIES:-4}"
RETRY_SLEEP="${RETRY_SLEEP:-10}"
# Alertmanager v2 API; empty disables. ALERT_DRILL=1 adds drill="true" (dev-only route).
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"
ALERT_DRILL="${ALERT_DRILL:-0}"
# ALERT_HOLD_SECONDS keeps a failure firing until the next daily run replaces it.
ALERT_HOLD_SECONDS="${ALERT_HOLD_SECONDS:-93600}"

# --- same-run alerting (fires on any non-zero exit, resolves on success) ---
alert() {
  local state="$1" summary="$2" ends
  [[ -n "$ALERTMANAGER_URL" ]] || return 0
  if [[ "$state" == "firing" ]]; then
    ends="$(date -u -d "@$(( $(date +%s) + ALERT_HOLD_SECONDS ))" '+%Y-%m-%dT%H:%M:%SZ')"
  else
    ends="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  fi
  local labels
  labels="$(jq -cn --arg drill "$ALERT_DRILL" '{alertname:"ObsArchiveFailed",class:"backup",severity:"critical",host:"contabo-a",job:"coolify-obs-archive"} + (if $drill == "1" then {drill:"true"} else {} end)')"
  jq -cn --argjson labels "$labels" --arg summary "$summary" --arg ends "$ends" \
    --arg desc "/usr/local/sbin/coolify-obs-archive.sh target_day=${TARGET_DAY:-?}; see /var/log/coolify-obs-archive.log on contabo-a" \
    '[{labels:$labels, annotations:{summary:$summary, description:$desc}, endsAt:$ends}]' \
    | curl -fsS -m 10 -X POST -H 'Content-Type: application/json' --data-binary @- \
        "${ALERTMANAGER_URL}/api/v2/alerts" >/dev/null \
    && log "alertmanager ${state}: ${summary}" \
    || log "WARN: could not post ${state} alert to ${ALERTMANAGER_URL}"
}
on_exit() {
  local rc=$?
  if [[ "$rc" -ne 0 ]]; then
    alert firing "obs archive FAILED day=${TARGET_DAY:-?} rc=${rc}: ${FAIL_REASON:-unexpected error (see log)}"
  fi
}
trap on_exit EXIT

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
utc() { date -u -d "@$1" '+%Y-%m-%dT%H:%M:%SZ'; }
START_UTC="$(utc "$START_EPOCH")"
END_UTC="$(utc "$END_EPOCH")"
DAY_PATH="$(TZ=Europe/Berlin date -d "${TARGET_DAY}" '+%Y/%m/%d')"
STAMP="$(TZ=Europe/Berlin date '+%Y%m%dT%H%M%z')"
# VL on-disk partitions are UTC YYYYMMDD; Berlin day can span 1–2 UTC days
UTC_DAY_START="$(date -u -d "@${START_EPOCH}" '+%Y%m%d')"
UTC_DAY_END="$(date -u -d "@$((END_EPOCH - 1))" '+%Y%m%d')"

mkdir -p "$WORKDIR"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another archive run is in progress (lock: $LOCK_FILE)"

# Per-run directory: never reuses or clobbers files left by earlier runs
# (e.g. preserved partial exports in $WORKDIR). Removed only after success.
RUN_DIR="${WORKDIR}/run-${TARGET_DAY}-${STAMP}-$$"
mkdir -p "$RUN_DIR"

log "start target_day=${TARGET_DAY} berlin day_path=${DAY_PATH} start_utc=${START_UTC} end_utc=${END_UTC} kinds=${KINDS} run_dir=${RUN_DIR}"

s3_uri() { printf 's3://%s/%s' "$S3_BUCKET" "$1"; }
aws_ep() { if [[ -n "$S3_ENDPOINT_URL" ]]; then aws "$@" --endpoint-url "$S3_ENDPOINT_URL"; else aws "$@"; fi; }
# Upload, then head-verify that the object exists with the local byte size.
s3_put_verified() {
  local src="$1" key="$2" want got i
  want="$(wc -c <"$src" | tr -d ' ')"
  for ((i = 1; i <= RETRIES; i++)); do
    if aws_ep s3 cp "$src" "$(s3_uri "$key")" --only-show-errors \
      && got="$(aws_ep s3api head-object --bucket "$S3_BUCKET" --key "$key" --query ContentLength --output text)" \
      && [[ "$got" == "$want" ]]; then
      log "verified $(s3_uri "$key") bytes=${got}"
      return 0
    fi
    log "WARN: upload/verify attempt ${i}/${RETRIES} failed for ${key} (want=${want} got=${got:-none})"
    sleep "$RETRY_SLEEP"
  done
  return 1
}

want_kind() { [[ " $KINDS " == *" $1 "* ]]; }
METRICS_KEY="-"
LOGS_KEY="-"

# --- metrics: VictoriaMetrics /api/v1/export ---
if want_kind metrics; then
  METRICS_RAW="${RUN_DIR}/metrics-${TARGET_DAY}.ndjson"
  METRICS_GZ="${METRICS_RAW}.gz"
  log "export metrics from ${VM_URL}"
  ok=0
  for ((i = 1; i <= RETRIES; i++)); do
    if curl -fsS -G "${VM_URL}/api/v1/export" \
      --data-urlencode 'match[]={__name__!=""}' \
      --data-urlencode "start=${START_UTC}" \
      --data-urlencode "end=${END_UTC}" \
      -o "$METRICS_RAW"; then
      ok=1; break
    fi
    log "WARN: VM export attempt ${i}/${RETRIES} failed"
    sleep "$RETRY_SLEEP"
  done
  [[ "$ok" -eq 1 ]] || fail "VM export failed after ${RETRIES} attempts"

  METRICS_BYTES="$(wc -c <"$METRICS_RAW" | tr -d ' ')"
  if [[ "$METRICS_BYTES" -eq 0 ]]; then
    log "WARN: metrics export empty for ${TARGET_DAY} (OK if stack <48h old)"
    printf '{"status":"empty","day":"%s","kind":"metrics"}\n' "$TARGET_DAY" >"$METRICS_RAW"
  fi
  gzip -c "$METRICS_RAW" >"$METRICS_GZ"
  METRICS_KEY="${S3_PREFIX}/metrics/${DAY_PATH}/metrics-${TARGET_DAY}-${STAMP}.ndjson.gz"
  log "upload metrics key=${METRICS_KEY} bytes_gz=$(wc -c <"$METRICS_GZ" | tr -d ' ')"
  s3_put_verified "$METRICS_GZ" "$METRICS_KEY" || fail "S3 upload/verify failed for metrics ${METRICS_KEY}"
fi

# --- logs: VictoriaLogs LogsQL, bounded windows ---
vl_count() {
  curl -fsS -m 120 "${VL_URL}/select/logsql/query" \
    --data-urlencode "query=_time:[$1,$2) | stats count() rows" \
    | jq -r '.rows // empty' | head -n1
}
if want_kind logs; then
  LOGS_GZ="${RUN_DIR}/logs-${TARGET_DAY}.ndjson.gz"
  MANIFEST="${RUN_DIR}/logs-${TARGET_DAY}.manifest.ndjson"
  : >"$LOGS_GZ"; : >"$MANIFEST"
  PART="${RUN_DIR}/window.ndjson"
  TOTAL_ROWS=0; ZERO_WINDOWS=0; NWIN=0
  log "export logs from ${VL_URL} in ${VL_WINDOW_SECONDS}s windows"
  for ((ws = START_EPOCH; ws < END_EPOCH; ws += VL_WINDOW_SECONDS)); do
    we=$(( ws + VL_WINDOW_SECONDS )); (( we > END_EPOCH )) && we=$END_EPOCH
    a="$(utc "$ws")"; b="$(utc "$we")"
    NWIN=$((NWIN + 1)); ok=0
    for ((i = 1; i <= RETRIES; i++)); do
      expected="$(vl_count "$a" "$b" || true)"
      if [[ ! "$expected" =~ ^[0-9]+$ ]]; then
        log "WARN: window [${a},${b}) count attempt ${i}/${RETRIES} failed"
        sleep "$RETRY_SLEEP"; continue
      fi
      if ! curl -fsS -m 600 "${VL_URL}/select/logsql/query" \
        --data-urlencode "query=_time:[${a},${b})" -o "$PART"; then
        log "WARN: window [${a},${b}) export attempt ${i}/${RETRIES} failed (curl)"
        sleep "$RETRY_SLEEP"; continue
      fi
      got="$(wc -l <"$PART" | tr -d ' ')"
      # complete = at least the counted rows, ends in newline, last line is JSON
      if [[ "$got" -lt "$expected" ]] \
        || { [[ -s "$PART" ]] && [[ "$(tail -c1 "$PART" | od -An -c | tr -d ' ')" != '\n' ]]; } \
        || { [[ -s "$PART" ]] && ! tail -n1 "$PART" | jq -e . >/dev/null 2>&1; }; then
        log "WARN: window [${a},${b}) attempt ${i}/${RETRIES} incomplete rows=${got} expected=${expected}"
        sleep "$RETRY_SLEEP"; continue
      fi
      ok=1; break
    done
    [[ "$ok" -eq 1 ]] || fail "VL export window [${a},${b}) failed after ${RETRIES} attempts"
    gzip -c "$PART" >>"$LOGS_GZ"
    [[ "$got" -eq 0 ]] && ZERO_WINDOWS=$((ZERO_WINDOWS + 1))
    TOTAL_ROWS=$((TOTAL_ROWS + got))
    jq -cn --arg s "$a" --arg e "$b" --argjson rows "$got" --argjson expected "$expected" \
      '{start:$s,end:$e,rows:$rows,expected:$expected}' >>"$MANIFEST"
  done
  rm -f "$PART"
  log "logs export complete windows=${NWIN} rows=${TOTAL_ROWS} zero_row_windows=${ZERO_WINDOWS}"
  [[ "$ZERO_WINDOWS" -gt 0 ]] && log "WARN: ${ZERO_WINDOWS} window(s) had 0 rows (expired locally or no ingest) — see manifest"
  if [[ "$TOTAL_ROWS" -eq 0 ]]; then
    log "WARN: logs export empty for ${TARGET_DAY} (OK if stack <48h old)"
    printf '{"status":"empty","day":"%s","kind":"logs"}\n' "$TARGET_DAY" | gzip -c >"$LOGS_GZ"
  fi
  gzip -t "$LOGS_GZ" || fail "gzip integrity check failed for ${LOGS_GZ}"
  LOGS_KEY="${S3_PREFIX}/logs/${DAY_PATH}/logs-${TARGET_DAY}-${STAMP}.ndjson.gz"
  log "upload logs key=${LOGS_KEY} bytes_gz=$(wc -c <"$LOGS_GZ" | tr -d ' ') rows=${TOTAL_ROWS}"
  s3_put_verified "$LOGS_GZ" "$LOGS_KEY" || fail "S3 upload/verify failed for logs ${LOGS_KEY}"
  s3_put_verified "$MANIFEST" "${LOGS_KEY%.ndjson.gz}.manifest.ndjson" \
    || fail "S3 upload/verify failed for logs manifest"
fi

# --- optional: drop closed VL UTC partitions fully older than retention window ---
# Only remove partitions whose UTC day is strictly before yesterday UTC, and only
# after S3 verify. Active today/yesterday partitions are never touched.
if [[ "$DROP_VL_PARTITION" == "1" ]] && want_kind logs; then
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

rm -rf "$RUN_DIR"
alert resolved "obs archive OK day=${TARGET_DAY}"
log "ALL_DONE day=${TARGET_DAY} metrics=${METRICS_KEY} logs=${LOGS_KEY}"
