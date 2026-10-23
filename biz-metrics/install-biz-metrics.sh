#!/usr/bin/env bash
# Operator-side installer. Root cron loads /etc/biz-metrics.env (0600).
# Host Python uses an isolated venv and least-privilege PostgreSQL roles.
set -euo pipefail
HOST="${1:?usage: install-biz-metrics.sh <ssh-host>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10)
[[ -z "${BIZ_METRICS_SSH_CONFIG:-}" ]] || SSH+=(-F "$BIZ_METRICS_SSH_CONFIG")
[[ -z "${BIZ_METRICS_SSH_IDENTITY:-}" ]] || SSH+=(-i "$BIZ_METRICS_SSH_IDENTITY")

# Copy only source; no generated files or credentials cross the boundary.
tar -C "$HERE" --exclude=__pycache__ --exclude='*.pyc' -cf - runner sql cron schema.sql roles.sql check-dump.sh provision-biz-metrics.py \
  | "${SSH[@]}" "$HOST" 'sudo -n mkdir -p /data/biz-metrics && sudo -n tar -xf - -C /data/biz-metrics'
"${SSH[@]}" "$HOST" sudo -n bash -s <<'REMOTE'
set -euo pipefail
zone="$(timedatectl show -p Timezone --value)"
[[ "$zone" == Europe/Berlin ]] || { echo 'Host timezone must be Europe/Berlin for Debian cron'; exit 1; }
python3 -m venv /data/biz-metrics/venv
/data/biz-metrics/venv/bin/pip install --quiet -r /data/biz-metrics/runner/requirements.txt
/data/biz-metrics/venv/bin/python -c 'import psycopg; print("runtime dependency OK")'
install -m 0755 /data/biz-metrics/cron/run.sh /data/biz-metrics/run.sh
if [[ ! -f /etc/biz-metrics.env ]]; then
  install -m 0600 /data/biz-metrics/cron/biz-metrics.env.example /etc/biz-metrics.env
  echo 'Created private configuration with placeholders; provision DB roles before first run'
fi
chown root:root /etc/biz-metrics.env
chmod 0600 /etc/biz-metrics.env
install -m 0644 /data/biz-metrics/cron/biz-metrics.cron /etc/cron.d/biz-metrics
touch /var/log/biz-metrics.log
chmod 0600 /var/log/biz-metrics.log
cat > /etc/logrotate.d/biz-metrics <<'ROTATE'
/var/log/biz-metrics.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0600 root root
}
ROTATE
bash -n /data/biz-metrics/run.sh
systemctl is-active --quiet cron
echo 'Installed nightly 01:30 Europe/Berlin schedule; configuration preserved'
REMOTE
