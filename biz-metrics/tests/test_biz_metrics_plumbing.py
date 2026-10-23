"""biz-metrics plumbing tests — collect-only (t1127u Intake A).

No live DB, no docker, no secrets. Product-metric behavior lives in
test_biz_metrics_cmp.py (plus relay/aisl siblings); this file guards the
plumbing contract: window math, VM payload shape, PII blocking, textfile
fallback, idempotent upsert SQL, cron/env/schema wiring, and collect-only
(no alert rules — deferred intake ab72bb5b).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_rollup():
    spec = importlib.util.spec_from_file_location(
        "biz_rollup_plumbing", str(ROOT / "runner" / "rollup.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["biz_rollup_plumbing"] = mod
    spec.loader.exec_module(mod)
    return mod


rollup = _load_rollup()


def test_window_days_is_d_minus_1_to_7_plumbing():
    assert rollup.window_days(7, dt.date(2026, 10, 22))[0] == dt.date(2026, 10, 21)
    assert len(rollup.window_days(7, dt.date(2026, 10, 22))) == 7


def test_today_so_far_resolves_to_single_day():
    args = rollup.parse_args(["--today-so-far"])
    assert rollup.resolve_days(args) == [rollup.utc_today()]


def test_render_sample_day_start_utc_ms_and_biz_prefix():
    line = rollup.render_sample(
        "relay_tx_messages",
        {"client": "acme", "status": "sent"},
        1234,
        dt.date(2026, 10, 21),
    )
    assert line == (
        'biz_relay_tx_messages{client="acme", status="sent"} 1234 1792540800000'
    )


def test_render_sample_drops_pii_labels():
    line = rollup.render_sample(
        "relay_tx_messages",
        {"client": "acme", "email": "a@x.y", "user_id": "7", "ip": "1.2.3.4"},
        5,
        dt.date(2026, 10, 21),
    )
    assert 'client="acme"' in line
    assert "email" not in line and "user_id" not in line and "ip=" not in line


def test_render_sample_truncates_long_values():
    line = rollup.render_sample("m", {"course": "x" * 200}, 1, dt.date(2026, 1, 1))
    assert len('course="{}"'.format("x" * 200)) > len(line)


def test_build_payload_sorted_for_goldens():
    rows = [
        {"series": "b", "dims": {}, "value": 2, "day": dt.date(2026, 10, 21)},
        {"series": "a", "dims": {}, "value": 1, "day": dt.date(2026, 10, 21)},
    ]
    payload = rollup.build_payload(rows)
    assert payload.index("biz_a{}") < payload.index("biz_b{}")
    assert payload.endswith("\n")


def test_upsert_sql_is_idempotent_named_params():
    assert "ON CONFLICT (day, project, metric, dims)" in rollup.UPSERT_SQL
    assert "DO UPDATE SET value = EXCLUDED.value" in rollup.UPSERT_SQL


class _FakeCursor:
    def __init__(self, fetch_rows=None):
        self.fetch_rows = fetch_rows or []
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.fetch_rows


class _FakeConn:
    def __init__(self, fetch_rows=None):
        self.cursors = []
        self.fetch_rows = fetch_rows

    def cursor(self):
        cur = _FakeCursor(self.fetch_rows)
        self.cursors.append(cur)
        return cur


def test_run_source_upserts_per_key_and_returns_vm_rows():
    dims = {"course": "mlops-zoomcamp", "homework": "hw1"}
    source = _FakeConn(fetch_rows=[(dt.date(2026, 10, 20), dict(dims), 2)])
    store = _FakeConn()
    metric = "cmp_homework_submissions"
    rows = rollup.run_source(
        source, store, metric, [dt.date(2026, 10, 20)], dry_run=False
    )
    assert rows == [{
        "series": "cmp_homework_submissions",
        "dims": {"platform": "cmp", **dims},
        "value": 2,
        "day": dt.date(2026, 10, 20),
    }]
    writes = [e for c in store.cursors for e in c.executed]
    assert len(writes) == 2
    sql, params = writes[1]
    assert "ON CONFLICT" in sql
    assert params["project"] == "cmp"
    assert json.loads(params["dims"])["platform"] == "cmp"
    # re-run is idempotent: same key shape, no duplicate statements per row
    store2 = _FakeConn()
    rollup.run_source(source, store2, metric, [dt.date(2026, 10, 20)], dry_run=False)
    assert len([e for c in store2.cursors for e in c.executed]) == 2


def test_registry_envs_all_documented():
    example = (ROOT / "cron" / "biz-metrics.env.example").read_text()
    for metric, (_project, dsn_env, _rel, _platform) in rollup.REGISTRY.items():
        assert dsn_env in example, metric
    assert "BIZ_METRICS_STORE_DSN" in example
    assert "VM_PUSH_URL" in example
    assert "BIZ_METRICS_RELAY_DSN" in example  # relay intake d9d8bd81


def test_registry_sql_files_exist():
    for metric, (_project, _dsn, relpath, _platform) in rollup.REGISTRY.items():
        assert (ROOT / "sql" / relpath).exists(), metric


def test_write_textfile_no_timestamps():
    rows = [
        {"series": "cmp_homework_submissions",
         "dims": {"platform": "cmp", "course": "c"}, "value": 3,
         "day": dt.date(2026, 10, 21)},
    ]
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = rollup.write_textfile(rows, tmp)
        text = Path(out).read_text()
    assert "# HELP biz_cmp_homework_submissions" in text
    assert "# TYPE biz_cmp_homework_submissions gauge" in text
    data = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert data and all(len(ln.rsplit(" ", 1)) == 2 for ln in data)


def test_cron_schedule():
    cron = (ROOT / "cron" / "biz-metrics.cron").read_text()
    assert "30 1" in cron and "Europe/Berlin" in cron
    assert "/data/biz-metrics/run.sh" in cron


def test_schema_has_pk_and_index():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "PRIMARY KEY (day, project, metric, dims)" in schema
    assert "metric_daily_project_metric_day_idx" in schema


def test_template_binds_window():
    tpl = (ROOT / "sql" / "_template.sql").read_text()
    assert "%(start)s" in tpl and "%(end)s" in tpl


def test_env_example_has_no_real_secrets():
    text = (ROOT / "cron" / "biz-metrics.env.example").read_text()
    assert "__REDACTED__" in text
    assert "BEGIN" not in text and "AKIA" not in text


def test_no_alert_rules_in_plumbing():
    """Collect-only: alert-rule payload or alert wiring must not exist."""
    markers = ("- alert:", "groups:", "rule_files", "smtplib", "send_alert",
               "check_threshold", "evaluate_rule", "vmalert_url",
               "alertmanager")
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in (".pyc", ".md") or path.name.startswith("test_"):
            continue
        if path.suffix not in (".py", ".sh", ".sql", ".cron", ".example"):
            continue
        text = path.read_text(errors="replace").lower()
        for marker in markers:
            assert marker not in text, f"alert marker {marker!r} in {path}"
    names = [p.name for p in ROOT.rglob("*")]
    assert not any(("alert" in n or "vmalert" in n)
                   and not n.startswith("test_") for n in names)
    assert not list(ROOT.glob("rules*.y*ml"))


def test_roles_separates_read_and_write():
    roles = (ROOT / "roles.sql").read_text()
    assert "biz_ro" in roles and "biz_rw" in roles
    assert "GRANT SELECT" in roles
    assert "PASSWORD" in roles  # placeholder marker only...
    assert "<from existing secrets path>" in roles  # ...never a real value
