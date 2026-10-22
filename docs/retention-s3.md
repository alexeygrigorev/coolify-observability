# Contabo obs retention + S3 archive (t1031u)

## Policy

| Tier | What | How long |
|------|------|----------|
| Hot (Contabo NVMe) | VM + VL local | **`-retentionPeriod=2d`** (~24–48h; yesterday stays queryable in vmui) |
| Warm (S3) | Closed day export | **14 days** lifecycle on `coolify/obs/` |
| Gone | After S3 expiry | Delete |

Daily job on **contabo-a** (`.163`): export **day-before-yesterday** (Europe/Berlin) → gzip → S3 → `head-object` verify. Local aged data drops via VM/VL retention (do **not** `rm` live VL partitions on v1.15.0 — no detach API).

## S3 layout

```
s3://dtc-coolify-backups-387546586013/coolify/obs/metrics/YYYY/MM/DD/metrics-<day>-<stamp>.ndjson.gz
s3://dtc-coolify-backups-387546586013/coolify/obs/logs/YYYY/MM/DD/logs-<day>-<stamp>.ndjson.gz
```

Same bucket + IAM user as Coolify Postgres dumps (`coolify-s3-backup-writer`, prefix `coolify/*`).

## Cron

`00:15` Europe/Berlin via `/etc/cron.d/coolify-obs-archive` → `/usr/local/sbin/coolify-obs-archive.sh`.

Early morning keeps nearly the full D-2 window inside a 2d retention before GC.

## Inspect an archived day

```bash
aws s3 cp s3://dtc-coolify-backups-387546586013/coolify/obs/logs/2026/10/20/logs-2026-10-20-….ndjson.gz - \
  | gunzip | head
```

Metrics are VictoriaMetrics `/api/v1/export` JSON lines; logs are VictoriaLogs LogsQL JSON lines.

## Files

| Path | Role |
|------|------|
| `docker-compose.prod.yml` | `-retentionPeriod=2d` on VM + VL |
| `scripts/obs-day-archive.sh` | export → S3 → verify |
| `scripts/coolify-obs-archive.cron` | cron.d fragment |
| `scripts/coolify-obs-archive.env.example` | `/etc/coolify-obs-archive.env` placeholders |
| `scripts/install-coolify-obs-archive.sh` | operator installer |
| `scripts/s3-lifecycle-obs.example.json` | bucket lifecycle (postgres 30d + obs 14d) |

## Install (operator)

```bash
./scripts/install-coolify-obs-archive.sh contabo-a
# fill /etc/coolify-obs-archive.env from ~/tmp/secrets/coolify-s3-backup-writer-*.env
# apply lifecycle (admin creds): aws s3api put-bucket-lifecycle-configuration …
```

Redeploy compose after retention flag change:

```bash
ssh contabo-a 'cd /data/obs && sudo docker compose up -d'
```

Do **not** break live scrapes: recreate only VM/VL (compose up -d); Vector keeps running if unchanged.
