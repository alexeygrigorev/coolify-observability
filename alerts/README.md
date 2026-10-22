# Alerts → destinée (`dev@dtcdev.click`)

OpenObserve scheduled alerts (preferred) for:

1. Disk ≥ 75–85%
2. Memory pressure
3. Host silence / missing telemetry (5m)
4. Postgres down (`pg_up == 0`)
5. Container restart loop
6. ERROR / log spike

SMTP: set `ZO_SMTP_*` in host `.env`. Until SMTP is wired, CI uses Mailpit (matrix A8).

Out-of-band dead-man: `machine-management/monitors/coolify-healthcheck` (add `/healthz` probe when UI DNS exists).
