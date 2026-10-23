"""biz-metrics AISHL P0 tests — collect-only (t1127u-D).

Part A (no DB): registry wiring (aishl entries, no platform injection),
SQL static checks (right tables/columns, UTC [start, end) params, no PII
in dims, no alert rules), VM payload rendering.
Part B (needs postgres): runs the real .sql files against fixture tables
mirroring the Django schema (analytics_useractivity /
analytics_userattribution / cb_curriculum_* / payments_*), incl. a
UTC-day-boundary row, unresolvable units, utm folding, and the WAU week
row. The container is started automatically; set SKIP_PG_FIXTURE=1 to
skip Part B when docker is unavailable.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql" / "aishl"


def _load_rollup():
    spec = importlib.util.spec_from_file_location(
        "biz_rollup", str(ROOT / "runner" / "rollup.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["biz_rollup"] = mod
    spec.loader.exec_module(mod)
    return mod


rollup = _load_rollup()

AISHL_METRICS = [
    "aishl_lesson_opens",
    "aishl_active_learners",
    "aishl_signups",
    "aishl_paid_conversions",
    "aishl_new_mrr_eur",
]

EXPECTED_DIMS = {
    "aishl_lesson_opens": {"course"},
    "aishl_active_learners": {"course", "grain"},
    "aishl_signups": {"utm_source"},
    "aishl_paid_conversions": {"tier", "billing_period", "utm_source"},
    "aishl_new_mrr_eur": {"tier", "billing_period", "utm_source"},
}


def _read(name: str) -> str:
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")


def _dims_expr(sql: str) -> str:
    code = re.sub(r"--.*", "", sql)  # ignore comments for token checks
    m = re.search(r"jsonb_build_object\((.*?)\)\s*AS dims",
                  code, re.IGNORECASE | re.DOTALL)
    assert m, "no jsonb_build_object(...) AS dims"
    return m.group(1)


def _dims_keys(sql: str) -> set[str]:
    """Keys of the jsonb_build_object dims: first item of each top-level pair."""
    expr = _dims_expr(sql)
    parts, depth, current = [], 0, ""
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    keys = set()
    for i in range(0, len(parts) - 1, 2):
        m = re.match(r"\s*'([a-z_]+)'\s*$", parts[i])
        assert m, f"dims key not a string literal: {parts[i]!r}"
        keys.add(m.group(1))
    return keys


# ---------- Part A: pure logic ----------


def test_registry_has_all_five_aishl_metrics_without_platform():
    for metric in AISHL_METRICS:
        project, dsn_env, relpath, platform = rollup.REGISTRY[metric]
        assert project == "aishl", metric
        assert dsn_env == "BIZ_METRICS_AISHL_DSN", metric
        assert (ROOT / "sql" / relpath).exists(), metric
        assert not platform, metric  # single aisl DB: empty disables injection


def test_sql_static_checks():
    for metric in AISHL_METRICS:
        sql = _read(metric)
        code = re.sub(r"--.*", "", sql)
        assert "AS day" in code, metric
        assert "AS dims" in code, metric
        assert "%(start)s" in code and "%(end)s" in code, metric
        # half-open UTC day window on the source timestamp, never a bare date
        assert re.search(r">=\s*%\(start\)s", code), metric
        assert re.search(r"<\s*%\(end\)s", code), metric
        # dims carry only the declared low-cardinality labels
        dims_keys = _dims_keys(sql)
        assert dims_keys == EXPECTED_DIMS[metric], (metric, dims_keys)
        # Inspect column identifiers; a literal source named email is safe.
        lowered = re.sub(r"'[^']*'", "", _dims_expr(sql)).lower()
        for token in ("email", "ip_address", "phone"):
            assert token not in lowered, (metric, token)
        assert "user_id" not in lowered, metric
        # collect-only: no thresholds or alert wiring in metric SQL
        for token in ("vmalert", "alert", "threshold", "for:", "grafana"):
            assert token not in code.lower(), (metric, token)


def test_run_source_skips_platform_for_aishl_and_upserts():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.executed.append((sql, params))

        def fetchall(self):
            return self.rows

    class FakeConn:
        def __init__(self, rows):
            self.cur = FakeCursor(rows)

        def cursor(self):
            return self.cur

    day = dt.date(2026, 10, 20)
    source = FakeConn([(day, {"utm_source": "telegram"}, 2)])
    store = FakeConn([])
    vm_rows = rollup.run_source(
        source, store, "aishl_signups", [day], dry_run=False)
    assert "platform" not in vm_rows[0]["dims"]
    assert vm_rows[0] == {"series": "aishl_signups",
                          "dims": {"utm_source": "telegram"},
                          "value": 2, "day": day}
    upsert_sql, params = store.cur.executed[-1]
    assert "ON CONFLICT (day, project, metric, dims)" in upsert_sql
    assert params["project"] == "aishl"
    assert params["metric"] == "aishl_signups"


def test_build_payload_sorts_and_prefixes_biz():
    rows = [
        {"series": "aishl_signups",
         "dims": {"utm_source": "telegram"}, "value": 2,
         "day": dt.date(2026, 10, 20)},
        {"series": "aishl_lesson_opens",
         "dims": {"course": "ml-bootcamp"}, "value": 12,
         "day": dt.date(2026, 10, 20)},
    ]
    payload = rollup.build_payload(rows)
    assert payload.splitlines() == [
        'biz_aishl_lesson_opens{course="ml-bootcamp"} 12 1792454400000',
        'biz_aishl_signups{utm_source="telegram"} 2 1792454400000',
    ]


# ---------- Part B: fixture DB ----------

FIXTURE_DDL = """
CREATE TABLE analytics_useractivity (
    id serial PRIMARY KEY,
    user_id integer NOT NULL,
    event_type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    object_type text NOT NULL DEFAULT '',
    object_id text NOT NULL DEFAULT ''
);
CREATE TABLE analytics_userattribution (
    user_id integer PRIMARY KEY,
    first_touch_utm_source text NOT NULL DEFAULT ''
);
CREATE TABLE cb_curriculum_course (id serial PRIMARY KEY, slug text NOT NULL);
CREATE TABLE cb_curriculum_module (id serial PRIMARY KEY, course_id integer NOT NULL);
CREATE TABLE cb_curriculum_unit (id serial PRIMARY KEY, module_id integer NOT NULL);
CREATE TABLE payments_tier (id serial PRIMARY KEY, slug text NOT NULL);
CREATE TABLE payments_conversionattribution (
    id serial PRIMARY KEY,
    tier_id integer NULL,
    billing_period text NOT NULL DEFAULT '',
    mrr_eur integer NULL,
    first_touch_utm_source text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE metric_daily (
    day date NOT NULL, project text NOT NULL, metric text NOT NULL,
    dims jsonb NOT NULL DEFAULT '{}'::jsonb, value numeric NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (day, project, metric, dims)
);
"""


def _start_postgres():
    name = "bizmetrics-pg-" + uuid.uuid4().hex[:12]
    r = subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name,
         "-e", "POSTGRES_PASSWORD=biztest",
         "-e", "POSTGRES_USER=biztest",
         "-e", "POSTGRES_DB=biztest",
         "-p", "127.0.0.1::5432",
         "postgres:16-alpine"],
        capture_output=True, text=True, check=False)
    if r.returncode != 0:
        pytest.skip(f"docker postgres unavailable: {r.stderr.strip()[:200]}")
    port = subprocess.check_output(
        ["docker", "port", name, "5432/tcp"], text=True).strip().rsplit(":", 1)[1]
    dsn = f"host=127.0.0.1 port={port} dbname=biztest user=biztest password=biztest"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            conn = __import__("psycopg").connect(dsn)
            conn.close()
            return dsn, name
        except Exception:
            time.sleep(1)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    pytest.skip("postgres container did not become ready")


@pytest.fixture(scope="module")
def pg_dsn():
    if os.environ.get("SKIP_PG_FIXTURE") == "1":
        pytest.skip("SKIP_PG_FIXTURE=1")
    pytest.importorskip("psycopg")
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True)
    except Exception:
        pytest.skip("docker not available")
    dsn, name = _start_postgres()
    yield dsn
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _load_fixture(conn) -> None:
    with conn.cursor() as cur:
        # courses: ml-bootcamp (module 1: units 1,2), llm-ops (module 2: unit 3)
        cur.execute("INSERT INTO cb_curriculum_course (slug) VALUES "
                    "('ml-bootcamp'), ('llm-ops') RETURNING id")
        c1, c2 = [r[0] for r in cur.fetchall()]
        cur.execute("INSERT INTO cb_curriculum_module (course_id) VALUES "
                    "(%s), (%s) RETURNING id", (c1, c2))
        m1, m2 = [r[0] for r in cur.fetchall()]
        cur.execute("INSERT INTO cb_curriculum_unit (module_id) VALUES "
                    "(%s), (%s), (%s) RETURNING id", (m1, m1, m2))
        u1, u2, u3 = [r[0] for r in cur.fetchall()]
        cur.execute("INSERT INTO payments_tier (slug) VALUES ('pro'), ('team') "
                    "RETURNING id")
        t_pro, t_team = [r[0] for r in cur.fetchall()]

        acts = [
            # (user_id, event, occurred_at ISO, object_type, object_id)
            # 00:30+03:00 on 10-20 == 21:30 UTC on 10-19 -> day boundary.
            (1, "lesson_open", "2026-10-20T00:30:00+03:00", "unit", str(u1)),
            (1, "lesson_open", "2026-10-20T10:00:00+00:00", "unit", str(u2)),
            (2, "lesson_open", "2026-10-20T11:00:00+00:00", "unit", str(u1)),
            (3, "lesson_open", "2026-10-20T12:00:00+00:00", "unit", str(u3)),
            (4, "lesson_open", "2026-10-21T09:00:00+00:00", "unit", str(u3)),
            (5, "lesson_open", "2026-10-20T13:00:00+00:00", "unit", "99999"),
            (6, "lesson_open", "2026-10-20T14:00:00+00:00", "unit", "not-a-pk"),
            (2, "resource_view", "2026-10-20T15:00:00+00:00", "article", "42"),
            (7, "resource_view", "2026-10-21T10:00:00+00:00", "tutorial", "7"),
            (10, "signup", "2026-10-20T08:00:00+00:00", "", ""),
            (11, "signup", "2026-10-20T09:00:00+00:00", "", ""),
            (12, "signup", "2026-10-20T10:00:00+00:00", "", ""),
            (13, "signup", "2026-10-21T08:00:00+00:00", "", ""),
            (1, "payment", "2026-10-20T16:00:00+00:00", "", ""),
        ]
        for user_id, event, ts, otype, oid in acts:
            cur.execute(
                "INSERT INTO analytics_useractivity "
                "(user_id, event_type, occurred_at, object_type, object_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, event, ts, otype, oid))
        for user_id, src in [(10, "Telegram"), (11, "telegram"), (12, ""),
                             (13, "Newsletter")]:
            cur.execute(
                "INSERT INTO analytics_userattribution (user_id, first_touch_utm_source)"
                " VALUES (%s, %s)", (user_id, src))
        convs = [
            # (tier_id, billing, mrr, utm, created_at ISO)
            (t_pro, "monthly", 29, "Telegram", "2026-10-20T10:00:00+00:00"),
            (t_pro, "yearly", 25, "", "2026-10-20T11:00:00+00:00"),
            (t_team, "monthly", 99, "newsletter", "2026-10-21T10:00:00+00:00"),
            (None, "", None, "", "2026-10-20T12:00:00+00:00"),
        ]
        for tier_id, billing, mrr, utm, ts in convs:
            cur.execute(
                "INSERT INTO payments_conversionattribution "
                "(tier_id, billing_period, mrr_eur, first_touch_utm_source, created_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (tier_id, billing, mrr, utm, ts))
    conn.commit()


def _run_day(conn, metric: str, day: dt.date):
    sql = (SQL_DIR / f"{metric}.sql").read_text(encoding="utf-8")
    start, end = rollup.day_bounds(day)
    with conn.cursor() as cur:
        cur.execute(sql, {"start": start, "end": end})
        assert [d[0] for d in cur.description] == ["day", "dims", "value"]
        return [(r[0].isoformat(), r[1], float(r[2])) for r in cur.fetchall()]


def _rows(rows):
    return {(day, json.dumps(dims, sort_keys=True)): value
            for day, dims, value in rows}


@pytest.fixture(scope="module")
def seeded_dsn(pg_dsn):
    import psycopg
    conn = psycopg.connect(pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(FIXTURE_DDL)
        conn.commit()
        _load_fixture(conn)
    finally:
        conn.close()
    return pg_dsn


def test_fixture_lesson_opens(seeded_dsn):
    import psycopg
    conn = psycopg.connect(seeded_dsn)
    try:
        got = _rows(_run_day(conn, "aishl_lesson_opens", dt.date(2026, 10, 19))
                    + _run_day(conn, "aishl_lesson_opens", dt.date(2026, 10, 20))
                    + _run_day(conn, "aishl_lesson_opens", dt.date(2026, 10, 21)))
    finally:
        conn.close()
    # 00:30+03:00 10-20 lands on UTC day 10-19; u1/u2 both ml-bootcamp.
    assert got == {
        ('2026-10-19', '{"course": "ml-bootcamp"}'): 1.0,
        ('2026-10-20', '{"course": "llm-ops"}'): 1.0,
        ('2026-10-20', '{"course": "ml-bootcamp"}'): 2.0,
        ('2026-10-20', '{"course": "unknown"}'): 2.0,  # 99999 + not-a-pk
        ('2026-10-21', '{"course": "llm-ops"}'): 1.0,
    }


def test_fixture_active_learners(seeded_dsn):
    import psycopg
    conn = psycopg.connect(seeded_dsn)
    try:
        got = _rows(_run_day(conn, "aishl_active_learners", dt.date(2026, 10, 20)))
    finally:
        conn.close()
    day = '{"course": "%s", "grain": "day"}'
    week = '{"course": "all", "grain": "week"}'
    assert got[('2026-10-20', day % "ml-bootcamp")] == 2.0   # users 1, 2
    assert got[('2026-10-20', day % "llm-ops")] == 1.0        # user 3
    assert got[('2026-10-20', day % "unknown")] == 2.0        # users 5, 6
    # overall DAU: distinct users 1,2,3,5,6 = 5 (resource_view user 2 deduped).
    assert got[('2026-10-20', day % "all")] == 5.0
    # WAU row: day = ISO Monday 10-19, full-week window, users 1..7 = 7.
    assert got[('2026-10-19', week)] == 7.0


def test_fixture_signups(seeded_dsn):
    import psycopg
    conn = psycopg.connect(seeded_dsn)
    try:
        got = _rows(_run_day(conn, "aishl_signups", dt.date(2026, 10, 20))
                    + _run_day(conn, "aishl_signups", dt.date(2026, 10, 21)))
    finally:
        conn.close()
    # Telegram / telegram fold together; '' folds to none.
    assert got == {
        ('2026-10-20', '{"utm_source": "telegram"}'): 2.0,
        ('2026-10-20', '{"utm_source": "none"}'): 1.0,
        ('2026-10-21', '{"utm_source": "newsletter"}'): 1.0,
    }


def test_fixture_paid_conversions_and_mrr(seeded_dsn):
    import psycopg
    conn = psycopg.connect(seeded_dsn)
    try:
        conv = _rows(_run_day(conn, "aishl_paid_conversions", dt.date(2026, 10, 20))
                     + _run_day(conn, "aishl_paid_conversions", dt.date(2026, 10, 21)))
        mrr = _rows(_run_day(conn, "aishl_new_mrr_eur", dt.date(2026, 10, 20))
                    + _run_day(conn, "aishl_new_mrr_eur", dt.date(2026, 10, 21)))
    finally:
        conn.close()
    assert conv == {
        ('2026-10-20',
         '{"billing_period": "monthly", "tier": "pro", "utm_source": "telegram"}'): 1.0,
        ('2026-10-20',
         '{"billing_period": "yearly", "tier": "pro", "utm_source": "none"}'): 1.0,
        ('2026-10-20',
         '{"billing_period": "one-off", "tier": "course", "utm_source": "none"}'): 1.0,
        ('2026-10-21',
         '{"billing_period": "monthly", "tier": "team", "utm_source": "newsletter"}'): 1.0,
    }
    assert mrr[('2026-10-20',
                '{"billing_period": "monthly", "tier": "pro", '
                '"utm_source": "telegram"}')] == 29.0
    assert mrr[('2026-10-20',
                '{"billing_period": "yearly", "tier": "pro", '
                '"utm_source": "none"}')] == 25.0
    # one-off NULL mrr sums to 0, row still present.
    assert mrr[('2026-10-20',
                '{"billing_period": "one-off", "tier": "course", '
                '"utm_source": "none"}')] == 0.0
    assert mrr[('2026-10-21',
                '{"billing_period": "monthly", "tier": "team", '
                '"utm_source": "newsletter"}')] == 99.0


def test_fixture_run_source_upsert_idempotent(seeded_dsn):
    import psycopg
    conn = psycopg.connect(seeded_dsn)
    try:
        rows = rollup.run_source(conn, conn, "aishl_signups",
                                 [dt.date(2026, 10, 20)], dry_run=False)
        assert len(rows) == 2
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM metric_daily "
                        "WHERE metric = 'aishl_signups'")
            assert cur.fetchone()[0] == 2
        # second run: same 2 rows, no duplicates.
        rollup.run_source(conn, conn, "aishl_signups",
                          [dt.date(2026, 10, 20)], dry_run=False)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM metric_daily "
                        "WHERE metric = 'aishl_signups'")
            assert cur.fetchone()[0] == 2
        with conn.cursor() as cur:
            cur.execute("SELECT dims::text, value FROM metric_daily "
                        "WHERE metric = 'aishl_signups' ORDER BY dims::text")
            stored = cur.fetchall()
        assert stored[0][1] == 1.0  # none
        assert stored[1][1] == 2.0  # telegram
    finally:
        conn.close()
