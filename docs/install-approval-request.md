# Install approval request — Coolify observability (VM+VL+Vector)

Date: 2026-10-26. Worker: obs-approval (Hub intake bc9b3f30, re-file of a478bb62 family).
Status: **NOT APPROVED — awaiting Alexey's explicit decision. No Contabo/Coolify write performed.**

## Candidate proposed for approval

- Repo: `coolify-observability`, exact commit `14a5167` (`fix(obs): correct p95 PromQL`, on top of `7329167` traefik/latency + `c67e247` A1–A8 drills).
- Scope: contents of `docker-compose.prod.yml` (project `coolify-obs-victoria` on contabo-a `.163`: VM `v1.115.0` + VL `v1.15.0` + Vector `0.60.0`, mem caps 256/256/128 MiB, retention `-retentionPeriod=2d`), `docker-compose.exporters.yml` (contabo-b `.141` Vector + node/postgres exporters), `configs/vm/prometheus.yml`, `configs/vector/contabo-{a,b}/vector.yaml`, `alerts/rules.yaml` (A1/A4/A6/A9 declarative; destinations **only** `dev@dtcdev.click` via coolify-healthcheck → SES), retention/S3 archive (`docs/retention-s3.md`, cron `00:15` Europe/Berlin).
- Targets/paths: `/data/obs/docker-compose.yml` on `.163`, `/data/obs-exporters/docker-compose.yml` on `.141`. Explicitly **not** starting `/data/openobserve/**` (stays STOPPED).

## Live verification already done (local, no prod touch)

- `python -m pytest tests/`: **14 passed** on 2026-10-26 (A1–A8 full matrix + latency suite), worktree at `14a5167`.
- `python -m pytest biz-metrics/tests/`: **77 passed, 11 skipped** (skips are live-DB only).
- No Hub, Contabo, Coolify, AWS, SMTP-secret, or mailbox access was used for this verification.

## What approval would authorize (and only this)

1. Deploy the exact commit above to the two paths above (compose up -d VM/VL/Vector + exporters only).
2. Install the S3 archive cron + lifecycle per `docs/retention-s3.md` (operator step, separate secrets file, not in repo).
3. Then run the production drill plan in `docs/production-drill-plan.md` (each class fires a real alert to `dev@dtcdev.click` and clears, with timestamps recorded).

Rollback: `docker compose down` of the `coolify-obs-victoria` project + restart prior exporter set; local 2d data is disposable, S3 archive (if any) retained per 14d lifecycle. No PG or app data touched.

## Decision needed from Alexey (one line suffices)

- `APPROVED: install 14a5167 to /data/obs (+exporters) and run production drills` — or
- `APPROVED WITH CHANGES: …` — or
- `DROP: do not install; close this line of work.`

No response = not approved. The worker will not install, reconfigure, restart, or fault-inject anything on Contabo/Coolify until that line exists.
