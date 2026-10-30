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
# msmtprc holds per-account blocks (account <name>: host/port/user/password).
# The global block uses the primary SES account (noreply@datatalks.club); the
# `alerts` account (alerts@dtcdev.click, f5d8e22b AC3 slowness sender) fills
# the slowness-dev receiver placeholders. AM runs as nobody (65534): chown so
# AM can read, others (non-root) cannot.
ssh "$HOST" 'sudo python3 - <<PY
import re, os, stat
src = open("/etc/msmtprc").read()
defaults, accounts, cur = {}, {}, None
for line in src.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if re.match(r"^account\s+default\s*:", line):
        cur = None
        continue
    m = re.match(r"^account\s+(\S+)$", line)
    if m:
        cur = m.group(1)
        accounts.setdefault(cur, {})
        continue
    m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*)\s+(\S+)$", line)
    if m:
        k, v = m.group(1), m.group(2)
        (defaults if cur is None else accounts[cur])[k] = v

def resolve(name):
    merged = dict(defaults)
    merged.update(accounts.get(name, {}))
    return merged

primary = accounts.get("ses") or next((a for a in accounts.values() if a.get("host")), {})
assert primary.get("host") and primary.get("user"), "primary SES account missing in msmtprc"
alerts = resolve("alerts")
assert alerts.get("host") and alerts.get("user") and alerts.get("password"), "alerts account missing in msmtprc (AC3 slowness sender)"
tmpl = open("/tmp/alertmanager.yml.template").read()
assert "__SMTP_SMARTHOST__" in tmpl, "template mismatch"
phost, pport = primary["host"], primary.get("port", "587")
puser, ppw = primary["user"], primary.get("password", "")
ahost, aport = alerts["host"], alerts.get("port", "587")
auser, apw = alerts["user"], alerts["password"]
out = tmpl.replace("__SMTP_SMARTHOST__", phost + ":" + pport)
out = out.replace("__SMTP_USER__", puser).replace("__SMTP_PASSWORD__", ppw)
out = out.replace("__SMTP_ALERTS_SMARTHOST__", ahost + ":" + aport)
out = out.replace("__SMTP_ALERTS_USER__", auser).replace("__SMTP_ALERTS_PASSWORD__", apw)
assert "__SMTP_" not in out, "unreplaced placeholder"
p = "/data/obs/alertmanager/alertmanager.yml"
open(p, "w").write(out)
os.chmod(p, 0o600)
os.chown(p, 65534, 65534)
print("wrote %s mode=600 owner=65534 user_len=%d pw_len=%d alerts_user_len=%d alerts_pw_len=%d" % (p, len(puser), len(ppw), len(auser), len(apw)))
PY'
ssh "$HOST" 'sudo rm -f /tmp/alertmanager.yml.template; sudo ls -l /data/obs/alertmanager/ /data/obs/configs/blackbox/ /data/obs/rules/'

echo "Configs synced. Next: deploy compose services from $REPO_DIR/docker-compose.yml"
echo "(operator: ssh $HOST 'cd /data/obs && sudo docker compose up -d blackbox vmalert-vm vmalert-vl alertmanager obs-a5-canary')"
echo "Then verify: curl localhost:9093/api/v2/status, :8880/api/v1/rules, :8881/api/v1/rules, and VM targets include blackbox-https."
