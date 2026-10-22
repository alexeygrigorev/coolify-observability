#!/usr/bin/env bash
# Install the nightly biz-metrics rollup on the data node (contabo-b).
# Run from an OPERATOR box — never install coding agents on Contabo prod boxes.
# Copies runner/ + sql/ to /data/biz-metrics, the wrapper to
# /data/biz-metrics/run.sh, creates /data/biz-metrics/env from the example if
# missing (you fill real DSNs on the node afterwards), and installs the cron
# fragment (01:30 Europe/Berlin daily, before the 02:30 pg_dump).
#
# Usage:
#   ./biz-metrics/install-biz-metrics.sh contabo-b
#   # then on the node (once): sudo nano /data/biz-metrics/env  (mode 600)
#   # verify: sudo -u biz-metrics /data/biz-metrics/run.sh --dry-run
#
# No secrets in git: this script never writes credentials; the env file on the
# node starts as placeholders and must be edited out-of-band.
set -euo pipefail

HOST="${1:-}"
if [[ -z "$HOST" ]]; then
  echo "usage: $0 <ssh-host>   (e.g. contabo-b)" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10)

echo "== copy runner to ${HOST} =="
scp -r "$HERE/runner" "$HERE/sql" "$HERE/cron/run.sh" "${HOST}:/tmp/biz-metrics-install/"
"${SSH[@]}" "$HOST" sudo bash -s <<'EOF'
set -euo pipefail
mkdir -p /data/biz-metrics
rm -rf /data/biz-metrics/runner /data/biz-metrics/sql
cp -r /tmp/biz-metrics-install/runner /data/biz-metrics/runner
cp -r /tmp/biz-metrics-install/sql /data/biz-metrics/sql
install -m 0755 /tmp/biz-metrics-install/run.sh /data/biz-metrics/run.sh
id biz-metrics >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin biz-metrics
python3 -c "import ast; ast.parse(open('/data/biz-metrics/runner/rollup.py').read()); print('rollup syntax OK')"
python3 -c "import sys; sys.path.insert(0, '/data/biz-metrics/runner'); import rollup; print('rollup import OK')"
pip install --quiet 'psycopg[binary]>=3.1' || pip3 install --quiet 'psycopg[binary]>=3.1' || echo "WARN: psycopg install failed — install manually"
EOF

echo "== env file (placeholders only; never overwritten) =="
scp "$HERE/cron/biz-metrics.env.example" "${HOST}:/tmp/biz-metrics.env.example"
"${SSH[@]}" "$HOST" 'sudo bash -s' <<'EOF'
set -euo pipefail
if [[ ! -f /data/biz-metrics/env ]]; then
  cp /tmp/biz-metrics.env.example /data/biz-metrics/env
  chmod 600 /data/biz-metrics/env
  chown root:biz-metrics /data/biz-metrics/env 2>/dev/null || true
  echo "created /data/biz-metrics/env (PLACEHOLDERS — edit on node, chmod 600)"
else
  echo "keep existing /data/biz-metrics/env (not overwritten)"
fi
EOF

echo "== cron entry (01:30 Europe/Berlin daily) =="
scp "$HERE/cron/biz-metrics.cron" "${HOST}:/tmp/biz-metrics.cron"
"${SSH[@]}" "$HOST" sudo install -m 0644 /tmp/biz-metrics.cron /etc/cron.d/biz-metrics

echo "== verify =="
"${SSH[@]}" "$HOST" 'sudo bash -n /data/biz-metrics/run.sh && echo SYNTAX_OK; cat /etc/cron.d/biz-metrics'
echo
echo "NEXT (operator, on ${HOST}):"
echo "  1. create DB + roles (see schema.sql / roles.sql), real DSNs in /data/biz-metrics/env"
echo "  2. add biz_metrics to PG_SHARED_DBS in /etc/coolify-pg-dump.env (see check-dump.sh)"
echo "  3. sudo -u biz-metrics /data/biz-metrics/run.sh --dry-run"
echo "  4. backfill: sudo -u biz-metrics /data/biz-metrics/run.sh --since YYYY-MM-DD --until YYYY-MM-DD"
echo "  5. confirm biz_* for yesterday in vmui"
