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

Hard caps: VM 256Mi / VL 256Mi / Vector 128Mi.

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

```bash
pip install -r tests/requirements.txt
docker compose -f docker-compose.test.yml --profile full up -d
python -m pytest tests/ -v
docker compose -f docker-compose.test.yml --profile full down -v
```

## Contabo paths

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
