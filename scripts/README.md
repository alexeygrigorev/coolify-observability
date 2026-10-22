# Scripts

| Script | Purpose |
|--------|---------|
| `obs-day-archive.sh` | Daily D-2 export (VM+VL) → S3; install as `/usr/local/sbin/coolify-obs-archive.sh` |
| `install-coolify-obs-archive.sh` | Operator installer (scp + cron + env placeholder) |
| `coolify-obs-archive.cron` | `00:15` Europe/Berlin cron.d fragment |
| `coolify-obs-archive.env.example` | `/etc/coolify-obs-archive.env` placeholders |
| `s3-lifecycle-obs.example.json` | Bucket lifecycle: postgres 30d + obs 14d |
| `soak-rss.sh` | RAM soak during 24–48h soak |
| `drill_alerter.py` | Thin custom alerter under CI drills |

See [`docs/retention-s3.md`](../docs/retention-s3.md).
