# coolify-observability

Lightweight observability for **Coolify on Contabo** (DataTalksClub / dtcdev).

## Recommended stack (plan + t1016u)

| Piece | Choice |
|-------|--------|
| **Primary** | **OpenObserve** (single binary/container on contabo-a `.163`) + **Vector** on `.163` and `.141` |
| Metrics + logs store | OpenObserve Parquet (+ WAL); SQLite metadata only — not a homemade TSDB |
| UI / alerts | OpenObserve UI + built-in alert destinations → **`dev@dtcdev.click`** |
| Dead-man | `machine-management/monitors/coolify-healthcheck` (cron → same mailbox) |
| **Fallback** if O2 RAM soak fails | **VictoriaMetrics + VictoriaLogs** (no Grafana) |
| Hard mem (OpenObserve) | **512–1024 MiB** initially; raise only after soak evidence |

See [TASKS.md](TASKS.md) for Hub child intakes (ids + links).

## Design principles

1. **Thin custom layer is OK** — collectors, alert rules, fault-injection drills. Do **not** reinvent a TSDB or log database.
2. **Storage = proven product** — OpenObserve (primary) or VictoriaMetrics/VictoriaLogs (fallback). No custom metrics/log stores.
3. **Docker alert fault-injection tests are mandatory** — every alert path must have a compose scenario that artificially causes the condition and asserts the alert fires (and recovers).
4. **Alerts → `dev@dtcdev.click`** — email is the default notification channel for operators.

## Scope

| In scope | Out of scope |
|----------|--------------|
| Host / container / Postgres / HTTPS health | Recreating LGTM (Prometheus+Loki+Grafana+AM zoo) |
| Alert rules + fault-injection CI | Writing a custom TSDB or log DB |
| Thin collectors (Vector) / OpenObserve | Secrets in git |
| Docs + test matrix A1–A8 | dataops-knowledge sprint dumps |

## Layout

```
.
├── README.md
├── TASKS.md                # Hub child tasks with ids/links
├── LICENSE                 # MIT
├── docker-compose.yml      # OpenObserve + Vector ( Contabo-shaped; pin tags )
├── docker-compose.test.yml # Alert drill stack (fault injection)
├── vector/                 # Vector configs for .163 / .141
├── alerts/                 # Alert rule stubs / OO alert definitions
├── scripts/                # Drill helpers + soak RSS sampler
├── tests/                  # pytest matrix for alert drills
└── docs/                   # CI pending + enable notes
```

## Alert fault-injection matrix

| ID | Condition | How we inject | Assert |
|----|-----------|---------------|--------|
| A1 | HTTPS endpoint down | Stop / blackhole target container | Alert fires within SLA; recovers when restored |
| A2 | Disk pressure | Fill a bind-mounted volume past threshold | Alert fires; recovers after cleanup |
| A3 | RAM / OOM pressure | Stress container or cgroup limit | Alert fires |
| A4 | Postgres unreachable | Stop PG or reject network | Alert fires; recovers |
| A5 | Coolify / app healthcheck fail | Force unhealthy healthcheck | Alert fires |
| A6 | Scrape / metrics gap | Pause exporter | Stale/missing-series alert fires |
| A7 | Log pipeline stall | Break shipper → OpenObserve | Pipeline-down alert fires |
| A8 | Alert email path | Capture SMTP (Mailpit) | Message to `dev@dtcdev.click` recorded |

## Local / CI test run

```bash
docker compose -f docker-compose.test.yml up -d --wait || true
python -m pytest tests/ -v
docker compose -f docker-compose.test.yml down -v
```

CI definition is at `docs/ci.yml.workflow-pending` (promote to `.github/workflows/ci.yml` once a token with the `workflow` scope is available — see `docs/ENABLE_GITHUB_ACTIONS.md`).

## Related

- Hub parent: https://hub.dtcdev.click/#/intake/a478bb62-ead3-4cce-a8cc-4a8897e7ca71
- Inventory / monitors: [`alexeygrigorev/machine-management`](https://github.com/alexeygrigorev/machine-management)
- Plan reports (operators): `~/tmp/agent-reports/obs-lightweight-plan-t1012u-*`

## License

MIT — see [LICENSE](LICENSE).
