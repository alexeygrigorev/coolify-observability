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

**Wired (t1028u)** via `coolify-healthcheck` → msmtp → SES (`noreply@datatalks.club`):

1. `dtcdev+5xx@mail.grokbot.com` (preferred tagged; ask Alexey later for final prod mailbox)
2. `dev@dtcdev.click` (keep working path)

See `alerts/destinations.example.yaml`. CI drills still assert both recipients via Mailpit.
Dead-man also probes VM/VL `/health` from both Contabo hosts.

## Layout

```
docker-compose.prod.yml       # .163 VM+VL+Vector (project coolify-obs-victoria)
docker-compose.exporters.yml  # .141 Vector
docker-compose.test.yml       # CI drills
configs/vm/prometheus.yml     # scrape targets
configs/vector/contabo-{a,b}/
alerts/                       # rules + deferred destinations
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
- Do **not** start `/data/openobserve/**` (STOPPED)

## License

MIT
