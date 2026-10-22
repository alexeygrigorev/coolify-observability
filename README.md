# coolify-observability

Lightweight observability for **Coolify on Contabo** (DataTalksClub / dtcdev).

## Design principles

1. **Thin custom layer is OK** — a small daemon, exporters, alert rules, and wiring. Do **not** reinvent a TSDB or log database.
2. **Storage = existing** — prefer battle-tested backends already in the stack or cheap to run: **VictoriaMetrics**, **VictoriaLogs**, Prometheus, Loki, Grafana, Alertmanager (or Grafana Cloud Free as a bootstrap). No custom metrics/log stores.
3. **Docker alert fault-injection tests are mandatory** — every alert path must have a compose scenario that artificially causes the condition and asserts the alert fires (and recovers).
4. **Alerts → `dev@dtcdev.click`** — email is the default notification channel for operators.

## Scope

| In scope | Out of scope (for now) |
|----------|-------------------------|
| Host / container / Postgres / HTTPS health | Full LGTM install on Contabo without a plan |
| Alert rules + fault-injection CI | Writing a custom TSDB or log DB |
| Thin collectors / scrapers / notifiers | Installing on Contabo from this repo until operators say go |
| Docs + test matrix | Secrets in git |

**Do not install on Contabo from CI or casual clones.** Deploy is a separate, explicit ops step after the Astra/Argon/Opus plan and Hub tasks land.

## Layout

```
.
├── README.md
├── LICENSE                 # MIT
├── docker-compose.test.yml # Alert drill stack (fault injection)
├── alerts/                 # Alert rule stubs (PromQL / vmalert / etc.)
├── scripts/                # Drill helpers (cause fault, wait, assert)
├── tests/                  # Python/pytest matrix for alert drills
└── .github/workflows/ci.yml
```

## Alert fault-injection matrix (target)

| ID | Condition | How we inject | Assert |
|----|-----------|---------------|--------|
| A1 | HTTPS endpoint down | Stop / blackhole target container | Alert fires within SLA; recovers when restored |
| A2 | Disk pressure | Fill a bind-mounted volume past threshold | Alert fires; recovers after cleanup |
| A3 | RAM / OOM pressure | Stress container or cgroup limit | Alert fires |
| A4 | Postgres unreachable | Stop PG or `pg_reject` network | Alert fires; recovers |
| A5 | Coolify / app healthcheck fail | Force unhealthy healthcheck | Alert fires |
| A6 | Scrape / metrics gap | Pause exporter | Stale/missing-series alert fires |
| A7 | Log pipeline stall | Break shipper → VictoriaLogs/Loki | Pipeline-down alert fires |
| A8 | Alert email path | Capture SMTP (Mailpit) | Message to `dev@dtcdev.click` recorded |

Exact thresholds and storage choice (VictoriaMetrics vs Prometheus, VictoriaLogs vs Loki) come from the peer plan (`obs-lightweight-plan-t1012u*`, `obs-rec-*-t1014u*`). This scaffold ships a **skipped** placeholder test documenting the matrix until rules exist.

## Local / CI test run

```bash
# Requires Docker. Tests skip until alert rules + injectors are implemented.
docker compose -f docker-compose.test.yml up -d --wait || true
python -m pytest tests/ -v
docker compose -f docker-compose.test.yml down -v
```

CI definition is at `docs/ci.yml.workflow-pending` (promote to `.github/workflows/ci.yml` once a token with the `workflow` scope is available — see `docs/ENABLE_GITHUB_ACTIONS.md`). It runs the same compose + pytest path on every push/PR to `main`.

## Related

- Inventory / monitors: [`alexeygrigorev/machine-management`](https://github.com/alexeygrigorev/machine-management)
- Prior LGTM design notes: Contabo Coolify observability reports under `~/tmp/agent-reports/coolify-observability-*` and `obs-lightweight-*` (operators only; not in this repo)

## License

MIT — see [LICENSE](LICENSE).
