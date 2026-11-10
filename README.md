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

Hard caps: VM 2Gi / VL 1Gi / Vector 128Mi / latency-VM 256Mi.

## HTTP response time + slowness (f5d8e22b)

Traefik Prometheus metrics on both proxies (internal `:8082`, bound to
`127.0.0.1` + `10.100.0.x` only — never public; see
machine-management `edge/install-traefik-metrics.sh`). VM scrapes over
WireGuard (`configs/vm/prometheus.yml` `traefik` job).

Latency store: `victoria-metrics-latency` on `.163` `:8429`
(`-retentionPeriod=30d`, 256Mi cap) holds low-cardinality series only
(traefik per-service + `probe_ttfb/total`). The main VM also retains 30d with
a 2Gi cap; cAdvisor scrapes both Contabo hosts, normalizes Coolify deploy-time
suffixes, and drops changing container IDs to keep series cardinality bounded.
VictoriaLogs retains 14d with a 1Gi cap so a failed daily archive can be
retried. Blackbox probes include AISHL and the production website at
15-second intervals. Probes:
`coolify-healthcheck` (Contabo) + `contabo-deadman` (Hetzner, via SSH)
record `probe_ttfb_seconds` / `probe_total_seconds` per URL for CMP home +
course, AISHL home + content, Relay /health, website home + /events/past, and
(since 2026-10-30, f5d8e22b AC1) the AWS-hosted services hub/ops/dapier —
they never pass through the Contabo Traefik proxies, so probes are their only
per-service latency source. Each monitor records the full URL set on every
run, including CMP home + the ML Zoomcamp course page; CMP `/api/health/`
checks remain separate from these page-level TTFB probes. The service label
lets the query below combine samples across Hetzner and both Contabo hosts.

### Proxy request attribution (F9)

Vector parses JSON access logs from `coolify-proxy` and writes only
`client_host`, `request_host`, `request_path`, `status`, `duration_ns`, and
`user_agent`, plus host/container/time metadata. Query strings are removed from
`request_path`; the original JSON line and all other access-log fields,
including headers and body-related fields, are discarded. Malformed proxy
lines are dropped. Vector unit tests for the allowlist and routing are in
`tests/vector-fable-accesslog.yaml`.

One PromQL p95 per service (30d, latency VM `:8429/vmui`):

```promql
# AC1 one-query p95 per service (all seven: cmp, aisl, relay, website, hub, ops, dapier; 30d)
max by (service) (quantile_over_time(0.95, probe_ttfb_seconds[30d]))
# Traefik per-service p95 (Contabo-fronted services, live)
histogram_quantile(0.95, sum by (service, le) (rate(traefik_service_request_duration_seconds_bucket[5m])))
# Raw probe series (pushed): max TTFB by probe/service
max by (probe, service) (probe_ttfb_seconds)
```

Slowness alert (AC3): service p95 > 2.5s OR probe TTFB > 3s for >=10m
→ mail ONLY `dev@dtcdev.click` from `alerts@dtcdev.click`, RECOVERED,
max 1/hour, hysteresis (recover <2.0s / <2.5s). Probe leg: monitor scripts.
Traefik p95 leg: native `obs-a10-slowness` vmalert rules with the same 2.0s
recovery hysteresis (ALERTS-based or-branch), routed by the alertmanager
`class="A10"` route to the `slowness-dev` receiver (dev@ only, per-config
`from alerts@dtcdev.click` via its own SES account, `send_resolved: true`).
Drills keep route precedence. See `alerts/rules.yaml` A10/A11.
Drill: injected-delay like A1-A8, ops-only, never mutes prod.

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

1. `dev@dtcdev.click` — shared ops inbox

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

Normal installations require an explicitly approved Contabo task after rule
and drill review. The Fable infra intake `3d787c10-1b64-45bb-827b-312dee3afc81`
authorizes applying these reviewed changes after merge. Use
`scripts/install-obs-alerting.sh` for timestamped config backups and apply only
the observability services; verify targets and loaded rules before finishing.

- `/data/obs/docker-compose.yml` on `.163`
- `/data/obs-exporters/docker-compose.yml` on `.141`
- `/data/lgtm/exporters/docker-compose.postgres.yml` on `.141`; see
  [Relay exporter routing and verification](docs/postgres-exporter-relay.md)
- Do **not** start `/data/openobserve/**` (STOPPED)

## Retention + S3 (t1031u)

| Tier | Policy |
|------|--------|
| Hot local | VM **`-retentionPeriod=30d`**, VL **`14d`** |
| Daily archive | day-before-yesterday → gzip → `s3://…/coolify/obs/{metrics,logs}/YYYY/MM/DD/` |
| S3 | lifecycle **14 days** on `coolify/obs/` |

Cron on `.163`: `00:15` Europe/Berlin → `/usr/local/sbin/coolify-obs-archive.sh`.  
Details: [`docs/retention-s3.md`](docs/retention-s3.md). Installer: `scripts/install-coolify-obs-archive.sh`.

## License

MIT

### Docker 29 cAdvisor upgrade

The old `gcr.io/cadvisor/cadvisor:v0.49.1` cannot discover Docker containers
using the containerd `overlayfs` image store: it looks for obsolete
`image/overlayfs/layerdb/mounts/*/mount-id` files. Use the pinned
`docker-compose.cadvisor.yml` exporter with the host `/var/run` mount (including
`containerd/containerd.sock`). It binds only loopback and WireGuard.

Upgrade one host at a time. Save the old exporter's inspect output and Compose
file in a root-only timestamped directory, pull the new image, then stop the old
exporter and start this Compose file from `/data/obs-cadvisor/` with
`CADVISOR_WG_IP=10.100.0.1` on contabo-a or `10.100.0.2` on contabo-b.
Keep the stopped old exporter for rollback; never remove its volumes. Confirm
`container_cpu_usage_seconds_total{name!=""}` includes app containers and
both `up{job="cadvisor"}` values are 1 before moving to the second host.
If validation fails, stop the new exporter and start the old one.

When replacing bind-mounted config files with `install-obs-alerting.sh`, apply
VM/VL using Compose, then force-recreate blackbox, vmalert-vm, vmalert-vl and
alertmanager with `--no-deps` so they mount and read the replacement files.
