#!/usr/bin/env bash
# One-time installer: SSH tunnel contabo-a -> hetzner for node_exporter (t1493u AC2).
# Lets contabo-a VictoriaMetrics scrape hetzner node metrics without a public port:
#   contabo-a 127.0.0.1:9102 --ssh--> hetzner 127.0.0.1:9100
# 9102 (not 9101): 9101 is contabo-a's own cadvisor.
# Run from the ops workstation (needs `ssh contabo-a` and `ssh hetzner` aliases).
# Idempotent; additive only (no deletions on either host).
# Key is generated ON contabo-a (root 600) and never leaves it; only the public
# key is copied to hetzner's authorized_keys with: forced /bin/false command, no
# pty/agent/X11, port-forwarding restricted to permitopen 127.0.0.1:9100,
# from=contabo-a public IP. Tunnel unit: obs-hetzner-node-tunnel.service.
set -euo pipefail

HETZNER_IP="${HETZNER_IP:-135.181.114.209}"
A_IP="${A_IP:-169.58.119.163}"
PORT="${PORT:-9102}"
KEY=/root/.ssh/id_ed25519_hetzner_nodeexport
UNIT=obs-hetzner-node-tunnel.service
MARK="obs-tunnel-nodeexport"

echo "== 1. keypair on contabo-a (root 600, generated on-host) =="
ssh -o BatchMode=yes contabo-a "sudo -n test -f $KEY || sudo -n ssh-keygen -t ed25519 -f $KEY -N '' -C '$MARK contabo-a-to-hetzner t1493u'
sudo -n chmod 600 $KEY
sudo -n cat $KEY.pub"

echo "== 2. pin hetzner host key in contabo-a root known_hosts (fingerprint check) =="
ssh -o BatchMode=yes contabo-a "sudo -n ssh-keyscan -t ed25519,rsa $HETZNER_IP 2>/dev/null | grep -v '^#' > /tmp/hz-kh
sudo -n ssh-keygen -lf /tmp/hz-kh
sudo -n bash -c 'touch /root/.ssh/known_hosts && cat /tmp/hz-kh >> /root/.ssh/known_hosts && sort -u -o /root/.ssh/known_hosts /root/.ssh/known_hosts && rm /tmp/hz-kh'"

echo "== 3. restricted pubkey on hetzner (append-only, backup kept) =="
PUB=$(ssh -o BatchMode=yes contabo-a "sudo -n cat $KEY.pub")
ssh -o BatchMode=yes hetzner "cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak-\$(date -u +%Y%m%dT%H%M%SZ)
grep -q '$MARK' ~/.ssh/authorized_keys || echo 'restrict,port-forwarding,permitopen=\"127.0.0.1:9100\",command=\"/bin/false\",from=\"$A_IP\" $PUB' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
grep -c '$MARK' ~/.ssh/authorized_keys"

echo "== 4. systemd unit on contabo-a =="
UNIT_FILE=$(mktemp)
cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=SSH tunnel contabo-a -> hetzner node_exporter (t1493u AC2, 127.0.0.1:$PORT)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ssh -N -T -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -i $KEY -L 127.0.0.1:$PORT:127.0.0.1:9100 alexey@$HETZNER_IP
Restart=always
RestartSec=15
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadOnlyPaths=/root/.ssh

[Install]
WantedBy=multi-user.target
UNIT
scp -q "$UNIT_FILE" contabo-a:/tmp/t1493u-unit
ssh -o BatchMode=yes contabo-a "sudo -n mv /tmp/t1493u-unit /etc/systemd/system/$UNIT
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now $UNIT"
rm -f "$UNIT_FILE"
sleep 5
ssh -o BatchMode=yes contabo-a "systemctl is-active $UNIT; curl -s -m 5 http://127.0.0.1:$PORT/metrics | head -1"

echo "== 5. scrape target: configs/vm/prometheus.yml already has 127.0.0.1:$PORT with host=hetzner =="
echo "Deploy it via scripts/install-obs-alerting.sh prometheus.yml section, then reload VM (/-/reload)."
