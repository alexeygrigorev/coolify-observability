# coolify-observability

Lightweight observability for **Coolify on Contabo**.

## Stack (t1014 consensus)

| Piece | Where | Notes |
|-------|-------|-------|
| **VictoriaMetrics** | contabo-a `.163` `:8428` | Native `promscrape` + **/vmui** (no Grafana) |
| **VictoriaLogs** | contabo-a `.163` `:9428` | **/select/vmui** |
| **Vector** | `.163` + `.141` | Docker logs → VL; host_metrics → VM |
| **Exporters** | `.141` | Keep node + postgres×2; drop promtail after Vector green |
| **coolify-healthcheck** | machine-management | Dead-man complement |

**Rejected for Contabo now:** OpenObserve (partial install torn down). Fallback remains documented only if VM/VL fails soak.

Hard caps: VM 256Mi / VL 256Mi / Vector 128Mi / latency-VM 256Mi.

## HTTP response time + slowness (f5d8e22b)

Traefik Prometheus metrics on both proxies (internal `:8082`, bound to
`127.0.0.1` + `10.100.0.x` only — never public; see
machine-management `edge/install-traefik-metrics.sh`). VM scrapes over
WireGuard (`configs/vm/prometheus.yml` `traefik` job).

Latency store: `victoria-metrics-latency` on `.163` `:8429`
(`-retentionPeriod=30d`, 256Mi cap) holds low-cardinality series only
(traefik per-service + `probe_ttfb/total`); main VM stays 2d (47k
node/cadvisor series would OOM at 30d under 256Mi). Probes:
`coolify-healthcheck` (Contabo) + `contabo-deadman` (Hetzner, via SSH)
record `probe_ttfb_seconds` / `probe_total_seconds` per URL for CMP home +
course, AISHL home + content, Relay /health, website home + /events/past.

One PromQL p95 per service (30d, latency VM `:8429/vmui`):

```promql
# Traefik per-service p95 (CMP, AISHL, Relay, website, ops, hub, dapier via service/router labels)
histogram_quantile(0.95, sum by (service, le) (rate(traefik_service_request_duration_seconds_bucket[5m])))
# Probe TTFB p95 per service (explicit service label, 30d)
max by (service) (quantile_over_time(0.95, probe_ttfb_seconds[1h]))
# Raw probe series (pushed): max TTFB by probe/service
max by (probe, service) (probe_ttfb_seconds)
```

Slowness alert (AC3): service p95 > 2.5s OR probe TTFB > 3s for >=10m
→ mail ONLY `dev@dtcdev.click` from `alerts@dtcdev.click`, RECOVERED,
max 1/hour, hysteresis (recover <2.0s / <2.5s). See `alerts/rules.yaml`
A10/A11. Drill: injected-delay like A1-A8, ops-only, never mutes prod.

AWS ALB history (AC5, read + S3 put only, profile `main-temp`, eu-west-1):

```
s3://dtc-coolify-backups-387546586013/coolify/obs/latency/alb/YYYY/MM/DD/alb-target-response-<day>.csv
```

Hourly `p50,p95,p99,SampleCount` for
`app/aisl-alb/…`, `app/course-management-shared/…`,
`app/website-production-alb/…` via `scripts/latency-alb-export.sh --day YYYY-MM-DD`
(ver 2026-10-18..24 exported; 10-23/24 empty — traffic on Contabo by then).

## Alert destinations

**Wired (t1029u)** via `coolify-healthcheck` → msmtp → SES (`noreply@datatalks.club`):

1. `alexey@datatalks.club` — Alexey (prod)
2. `dev@dtcdev.click` — shared ops inbox

`dtcdev+5xx@mail.grokbot.com` stays off Contabo prod alert lists unless needed for bot wake.

See `alerts/destinations.example.yaml`. CI drill A8 asserts the single recipient via Mailpit.
Dead-man also probes VM/VL `/health` from both Contabo hosts.

## Layout

```
docker-compose.prod.yml       # .163 VM+VL+Vector (project coolify-obs-victoria)
docker-compose.exporters.yml  # .141 Vector
docker-compose.postgres.yml   # .141 Postgres exporters (lgtm-pgexp)
docker-compose.test.yml       # CI drills
configs/vm/prometheus.yml     # scrape targets
configs/vector/contabo-{a,b}/
alerts/                       # rules + deferred destinations
biz-metrics/                  # nightly business rollup (collect-only, t1127u)
scripts/drill_alerter.py      # thin custom layer under test
tests/                        # A1–A8 fault-injection
```

## Local drills

Docker alert fault-injection is mandatory for the thin custom alert layer.
Storage stays in existing VictoriaMetrics/VictoriaLogs; this repo does not build
a storage engine. See [the A1–A8 matrix](tests/README.md) for bounded drills,
near-misses, FIRE/CLEAR SMTP capture, cleanup and the older-plan ID mapping.
All eight scenarios execute; no expected failures are accepted. Pytest owns the
isolated Compose lifecycle, generated TLS fixtures and ephemeral Mailpit port.

```bash
python -m pip install -r tests/requirements.txt
python -m pytest tests/ -v --tb=short
```

## Contabo paths

Installation requires a separate, explicitly approved Contabo task after rule
and drill review. This repository/plan task does not authorize installation or
a Coolify deployment.

- `/data/obs/docker-compose.yml` on `.163`
- `/data/obs-exporters/docker-compose.yml` on `.141`
- `/data/lgtm/exporters/docker-compose.postgres.yml` on `.141`; see
  [Relay exporter routing and verification](docs/postgres-exporter-relay.md)
- Do **not** start `/data/openobserve/**` (STOPPED)

## Retention + S3 (t1031u)

| Tier | Policy |
|------|--------|
| Hot local | VM + VL **`-retentionPeriod=2d`** (yesterday stays in vmui) |
| Daily archive | day-before-yesterday → gzip → `s3://…/coolify/obs/{metrics,logs}/YYYY/MM/DD/` |
| S3 | lifecycle **14 days** on `coolify/obs/` |

Cron on `.163`: `00:15` Europe/Berlin → `/usr/local/sbin/coolify-obs-archive.sh`.  
Details: [`docs/retention-s3.md`](docs/retention-s3.md). Installer: `scripts/install-coolify-obs-archive.sh`.

## License

MIT
