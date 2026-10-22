# Alert rules

Place Prometheus / vmalert / Alertmanager rule files here once the peer plan
chooses storage (VictoriaMetrics vs Prometheus, etc.).

Every rule must have a matching fault-injection case in `tests/` and a drill
helper under `scripts/`. Alerts notify **`dev@dtcdev.click`**.
