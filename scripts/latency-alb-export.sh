#!/usr/bin/env bash
# Export AWS ALB TargetResponseTime history (f5d8e22b AC5).
# Read-only CloudWatch + S3 put only. No other AWS writes.
#
# LBs (eu-west-1, MAIN 387546586013, profile main-temp):
#   app/aisl-alb/6df23474f6be1898
#   app/course-management-shared/bd279e4cc4f97601
#   app/website-production-alb/2a29241e78d66f7b
#
# Output: hourly p50/p95/p99 CSV+JSON to
#   s3://dtc-coolify-backups-387546586013/coolify/obs/latency/alb/YYYY/MM/DD/alb-target-response-<day>.csv
# Path documented in coolify-observability README.
#
# Usage:
#   ./scripts/latency-alb-export.sh [--day YYYY-MM-DD] [--dry-run]
#   AWS_PROFILE=main-temp ./scripts/latency-alb-export.sh --day 2026-10-24
set -euo pipefail

PROFILE="${AWS_PROFILE:-main-temp}"
REGION="${AWS_REGION:-eu-west-1}"
BUCKET="${S3_BUCKET:-dtc-coolify-backups-387546586013}"
PREFIX="${S3_PREFIX:-coolify/obs/latency/alb}"
DAY=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --day) DAY="${2:-}"; shift 2;;
    --day=*) DAY="${1#--day=}"; shift;;
    --dry-run) DRY_RUN=1; shift;;
    *) echo "unknown arg $1"; exit 1;;
  esac
done
if [[ -z "$DAY" ]]; then
  DAY="$(TZ=Europe/Berlin date -d 'yesterday' '+%Y-%m-%d')"
fi
START="$(date -u -d "$DAY 00:00:00" '+%Y-%m-%dT%H:%M:%SZ')"
END="$(date -u -d "$DAY + 1 day" '+%Y-%m-%dT%H:%M:%SZ')"
DAY_PATH="$(date -u -d "$DAY" '+%Y/%m/%d')"

LBS=(
  "app/aisl-alb/6df23474f6be1898"
  "app/course-management-shared/bd279e4cc4f97601"
  "app/website-production-alb/2a29241e78d66f7b"
)

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/alb-target-response-$DAY.csv"
echo "timestamp,load_balancer,p50,p95,p99,sample_count" > "$OUT"

for lb in "${LBS[@]}"; do
  for stat in p50 p95 p99; do
    : # per-stat fetched together below
  done
  aws --profile "$PROFILE" --region "$REGION" cloudwatch get-metric-statistics \
    --namespace AWS/ApplicationELB \
    --metric-name TargetResponseTime \
    --dimensions Name=LoadBalancer,Value="$lb" \
    --start-time "$START" --end-time "$END" --period 3600 \
    --statistics SampleCount --extended-statistics p50 p95 p99 \
    --output json > "$WORK/$(echo "$lb" | tr '/_' '--').json"
done

python3 - "$WORK" "$OUT" "$DAY" <<'PY'
import json, sys, glob, csv, os
work, out, day = sys.argv[1], sys.argv[2], sys.argv[3]
rows = {}
for jf in glob.glob(os.path.join(work, "*.json")):
    lb = os.path.basename(jf)[:-5].replace("--", "/", 1)
    data = json.load(open(jf))
    for dp in data.get("Datapoints", []):
        ts = dp["Timestamp"]
        key = (ts, lb)
        r = rows.setdefault(key, {"p50": "", "p95": "", "p99": "", "count": dp.get("SampleCount", "")})
        for k in ("p50", "p95", "p99"):
            v = dp.get("ExtendedStatistics", {}).get(k)
            if v is not None:
                r[k] = f"{v:.4f}"
with open(out, "a", newline="") as f:
    w = csv.writer(f)
    for (ts, lb) in sorted(rows):
        r = rows[(ts, lb)]
        w.writerow([ts, lb, r["p50"], r["p95"], r["p99"], r["count"]])
print(f"wrote {len(rows)} hourly rows to {out}")
PY

KEY="$PREFIX/$DAY_PATH/alb-target-response-$DAY.csv"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY-RUN: would put $OUT -> s3://$BUCKET/$KEY"
  head -n 10 "$OUT"
else
  aws --profile "$PROFILE" --region "$REGION" s3 cp "$OUT" "s3://$BUCKET/$KEY" --only-show-errors
  aws --profile "$PROFILE" --region "$REGION" s3api head-object --bucket "$BUCKET" --key "$KEY" >/dev/null
  echo "OK s3://$BUCKET/$KEY"
fi
