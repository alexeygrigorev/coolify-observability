#!/usr/bin/env bash
# Install vmalert + Alertmanager + blackbox on contabo-a (operator step).
# Approved by DECISION t1468u (bc9b3f30). Drills to dev@ only. Never mute real prod alerts.
# Secrets: NEVER in git. SMTP creds are read ON-HOST from /etc/msmtprc (root 600)
# and written to /data/obs/alertmanager/alertmanager.yml (600). This script prints
# only redacted confirmation (host, user length, file mode), never values.
set -euo pipefail

HOST="${1:-contabo-a}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "== obs-alerting install to $HOST (additive, no PG/app touch) =="
ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" 'sudo mkdir -p /data/obs/alertmanager /data/obs/rules /data/obs/configs/blackbox /data/alertmanager-data && sudo chmod 700 /data/obs/alertmanager && sudo chown -R 65534:65534 /data/alertmanager-data && sudo chmod 700 /data/alertmanager-data && echo "dirs ok"'

# Sync reviewed configs (no secrets in repo).
scp "$REPO_DIR/configs/vmalert/rules-vm.yml" "$HOST:/tmp/rules-vm.yml"
scp "$REPO_DIR/configs/vmalert/rules-vl.yml" "$HOST:/tmp/rules-vl.yml"
scp "$REPO_DIR/configs/alertmanager/alertmanager.yml.template" "$HOST:/tmp/alertmanager.yml.template"
scp "$REPO_DIR/configs/blackbox/blackbox.yml" "$HOST:/tmp/blackbox.yml"
scp "$REPO_DIR/configs/vm/prometheus.yml" "$HOST:/tmp/prometheus.yml"
scp "$REPO_DIR/docker-compose.yml" "$HOST:/tmp/docker-compose.yml.new"

ssh "$HOST" 'sudo mv /tmp/rules-vm.yml /tmp/rules-vl.yml /data/obs/rules/ && sudo chmod 644 /data/obs/rules/*.yml && ls -l /data/obs/rules/'
ssh "$HOST" 'sudo mv /tmp/blackbox.yml /data/obs/configs/blackbox/blackbox.yml && sudo chmod 644 /data/obs/configs/blackbox/blackbox.yml && ls -l /data/obs/configs/blackbox/'
# Backup + sync prometheus scrape config (adds blackbox-https job). VM hot-reloads,
# but if targets do not appear within 90s, operator restarts victoria-metrics (data preserved).
ssh "$HOST" 'sudo cp /data/obs/configs/vm/prometheus.yml /data/obs/configs/vm/prometheus.yml.bak-$(date -u +%Y%m%dT%H%M%SZ) && sudo mv /tmp/prometheus.yml /data/obs/configs/vm/prometheus.yml && sudo chmod 644 /data/obs/configs/vm/prometheus.yml && echo "prometheus synced (backup kept)"'
# Backup + sync compose (adds blackbox/vmalert/AM/canary, no changes to VM/VL/Vector).
ssh "$HOST" 'sudo cp /data/obs/docker-compose.yml /data/obs/docker-compose.yml.bak-$(date -u +%Y%m%dT%H%M%SZ) && sudo mv /tmp/docker-compose.yml.new /data/obs/docker-compose.yml && sudo chmod 644 /data/obs/docker-compose.yml && echo "compose synced (backup kept)"'

# Inject SMTP creds on-host from /etc/msmtprc (root 600) without printing values.
# msmtprc format: host ..., port ..., user ..., password ..., from ...
# AM runs as nobody (65534): chown so AM can read, others (non-root) cannot.
ssh "$HOST" 'sudo python3 - <<PY
import re, os, stat
src = open("/etc/msmtprc").read()
def grab(k):
    m = re.search(rf"^{k}\s+(\S+)", src, re.M)
    return m.group(1) if m else ""
host = grab("host"); port = grab("port") or "587"; user = grab("user"); pw = grab("password")
tmpl = open("/tmp/alertmanager.yml.template").read()
assert "__SMTP_SMARTHOST__" in tmpl, "template mismatch"
out = tmpl.replace("__SMTP_SMARTHOST__", f"{host}:{port}").replace("__SMTP_USER__", user).replace("__SMTP_PASSWORD__", pw)
assert "__SMTP_" not in out, "unreplaced placeholder"
p = "/data/obs/alertmanager/alertmanager.yml"
open(p, "w").write(out)
os.chmod(p, 0o600)
os.chown(p, 65534, 65534)
print(f"wrote {p} mode=600 owner=65534 user_len={len(user)} pw_len={len(pw)}")
PY'
ssh "$HOST" 'sudo rm -f /tmp/alertmanager.yml.template; sudo ls -l /data/obs/alertmanager/ /data/obs/configs/blackbox/ /data/obs/rules/'

echo "Configs synced. Next: deploy compose services from $REPO_DIR/docker-compose.yml"
echo "(operator: ssh $HOST 'cd /data/obs && sudo docker compose up -d blackbox vmalert-vm vmalert-vl alertmanager obs-a5-canary')"
echo "Then verify: curl localhost:9093/api/v2/status, :8880/api/v1/rules, :8881/api/v1/rules, and VM targets include blackbox-https."
