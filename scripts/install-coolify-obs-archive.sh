#!/usr/bin/env bash
# Install daily obs day-archive → S3 on contabo-a (.163).
# Run from an OPERATOR box (Hetzner / box), not as a coding agent on Contabo.
#
# Usage:
#   ./scripts/install-coolify-obs-archive.sh contabo-a
set -euo pipefail

HOST="${1:-}"
if [[ -z "$HOST" ]]; then
  echo "usage: $0 <ssh-host>   (e.g. contabo-a)" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10)

echo "== copy archive script to ${HOST} =="
scp "${HERE}/obs-day-archive.sh" "${HOST}:/tmp/coolify-obs-archive.sh"
"${SSH[@]}" "$HOST" sudo install -m 0755 /tmp/coolify-obs-archive.sh /usr/local/sbin/coolify-obs-archive.sh

echo "== env file (placeholders only; never overwritten) =="
scp "${HERE}/coolify-obs-archive.env.example" "${HOST}:/tmp/coolify-obs-archive.env.example"
"${SSH[@]}" "$HOST" 'sudo bash -s' <<'REMOTE'
set -euo pipefail
if [[ ! -f /etc/coolify-obs-archive.env ]]; then
  install -m 0600 /tmp/coolify-obs-archive.env.example /etc/coolify-obs-archive.env
  echo "created /etc/coolify-obs-archive.env (PLACEHOLDERS — edit on node)"
else
  echo "keep existing /etc/coolify-obs-archive.env (not overwritten)"
fi
mkdir -p /var/tmp/coolify-obs-archive
touch /var/log/coolify-obs-archive.log
chmod 0644 /var/log/coolify-obs-archive.log
command -v aws >/dev/null || echo "WARN: aws cli missing — pip/apt install awscli"
REMOTE

echo "== cron entry (00:15 Europe/Berlin daily) =="
scp "${HERE}/coolify-obs-archive.cron" "${HOST}:/tmp/coolify-obs-archive.cron"
"${SSH[@]}" "$HOST" sudo install -m 0644 /tmp/coolify-obs-archive.cron /etc/cron.d/coolify-obs-archive

echo "== verify =="
"${SSH[@]}" "$HOST" 'sudo bash -n /usr/local/sbin/coolify-obs-archive.sh && echo SYNTAX_OK; cat /etc/cron.d/coolify-obs-archive'
echo
echo "NEXT: put real AWS keys in /etc/coolify-obs-archive.env on ${HOST}, then:"
echo "  ssh ${HOST} 'sudo TARGET_DAY=\$(TZ=Europe/Berlin date -d yesterday +%Y-%m-%d) /usr/local/sbin/coolify-obs-archive.sh'"
echo "S3 layout: s3://<bucket>/coolify/obs/{metrics,logs}/YYYY/MM/DD/"
