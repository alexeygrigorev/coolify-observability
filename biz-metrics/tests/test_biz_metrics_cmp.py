"""biz-metrics CMP P0 tests — collect-only (t1127u).

Part A (no DB): window math, VM payload rendering, registry/SQL consistency,
SQL static checks (right tables/columns, no PII, no alert rules).
Part B (needs postgres): set BIZMETRICS_TEST_DSN to run the real .sql files
against fixture tables mirroring the Django schema, incl. the
submitted_at resubmit-bump semantics.

Local run for Part B:
  docker run --rm -d --name biztest -e POSTGRES_PASSWORD=x -p 55433:5432 postgres:16-alpine
  BIZMETRICS_TEST_DSN=postgresql://postgres:x@127.0.0.1:55433/postgres \
    python3 -m pytest biz-metrics/tests/test_biz_metrics_cmp.py -v
  docker stop biztest
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql" / "cmp"


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


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


# ---------- Part A: pure logic ----------


def test_window_days_is_d_minus_1_to_7():
    today = dt.date(2026, 10, 22)
    assert rollup.window_days(7, today) == [
        dt.date(2026, 10, 21),
        dt.date(2026, 10, 20),
        dt.date(2026, 10, 19),
        dt.date(2026, 10, 18),
        dt.date(2026, 10, 17),
        dt.date(2026, 10, 16),
        dt.date(2026, 10, 15),
    ]


def test_resolve_days_backfill_range():
    args = rollup.parse_args(["--since", "2026-10-18", "--until", "2026-10-21"])
    assert rollup.resolve_days(args) == [
        dt.date(2026, 10, 18),
        dt.date(2026, 10, 19),
        dt.date(2026, 10, 20),
    ]


def test_render_sample_has_day_start_utc_ms_and_biz_prefix():
    line = rollup.render_sample(
        "cmp_homework_submissions",
        {"platform": "cmp", "course": "mlops-zoomcamp", "homework": "hw1"},
        12,
        dt.date(2026, 10, 20),
    )
    assert line == (
        'biz_cmp_homework_submissions{course="mlops-zoomcamp", '
        'homework="hw1", platform="cmp"} 12 1792454400000'
    )


def test_render_sample_escapes_labels():
    line = rollup.render_sample("m", {"course": 'a"b\\c'}, 1, dt.date(2026, 1, 1))
    assert 'course="a\\"b\\\\c"' in line


def test_registry_sql_files_exist_and_platforms_cover_both_dbs():
    for metric, (project, _dsn, relpath, platform) in rollup.REGISTRY.items():
        assert (ROOT / "sql" / relpath).exists(), metric
        assert project == "cmp"
    platforms = {
        m: rollup.REGISTRY[m][3] for m in rollup.REGISTRY
    }
    assert set(platforms.values()) == {"cmp", "website"}
    # one SQL file serves both DBs for homework; registrations diverge
    assert (
        rollup.REGISTRY["cmp_homework_submissions"][2]
        == rollup.REGISTRY["cmp_homework_submissions_website"][2]
    )
    assert (
        rollup.REGISTRY["cmp_course_registrations"][2]
        != rollup.REGISTRY["cmp_course_registrations_website"][2]
    )


def test_sql_static_checks():
    hw = _read("cmp_homework_submissions.sql")
    reg = _read("cmp_course_registrations.sql")
    regw = _read("cmp_course_registrations_website.sql")
    for sql, name in ((hw, "hw"), (reg, "reg"), (regw, "regw")):
        code = re.sub(r"--.*", "", sql)  # ignore comments for token checks
        # returns (day, dims, value); jsonb dims; UTC day grain
        assert "AS day" in code, name
        assert "AS dims" in code, name
        assert "AS value" in code, name
        assert "jsonb_build_object" in code, name
        assert "AT TIME ZONE 'UTC'" in code, name
        assert "%(start)s" in code and "%(end)s" in code, name
        # no PII dimensions ever
        for banned in ("email", "user_id", "student_id", "ip_address",
                       "ipaddress", "user-id"):
            assert banned not in code.lower(), (name, banned)
        # collect-only: no alert/threshold content
        for banned in ("alert", "vmalert", "for:", "threshold"):
            assert banned not in code.lower(), (name, banned)
    # real Django tables (verified via Model._meta.db_table 2026-10-22)
    assert "courses_submission" in hw
    assert "submitted_at" in hw
    assert "courses_homework" in hw and "courses_course" in hw
    assert "courses_courseregistration" in reg
    assert "created_at" in reg and "'status', r.status" in reg
    assert "courses_registrationcampaign" in reg
    # website twin: no status column exists, so none referenced
    regw_code = re.sub(r"--.*", "", regw)
    assert "status" not in regw_code.lower()
    assert "courses_courseregistration" in regw


def test_schema_has_single_table_pk():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "metric_daily" in schema
    assert "PRIMARY KEY (day, project, metric, dims)" in schema
    assert "value NUMERIC" in schema


# ---------- Part B: live SQL against fixture tables ----------

TEST_DSN = os.environ.get("BIZMETRICS_TEST_DSN", "")


@pytest.fixture(scope="module")
def pg():
    if not TEST_DSN:
        pytest.skip("BIZMETRICS_TEST_DSN not set")
    pytest.importorskip("psycopg")
    import psycopg

    conn = psycopg.connect(TEST_DSN, autocommit=True)
    yield conn
    conn.close()


def _exec(conn, sql: str, params: dict | None = None):
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001 — DDL returns no rows
            return []


FIXTURES = """
DROP TABLE IF EXISTS courses_submission, courses_homework, courses_course,
    courses_courseregistration, courses_registrationcampaign;
CREATE TABLE courses_course (id SERIAL PRIMARY KEY, slug TEXT NOT NULL);
CREATE TABLE courses_homework (id SERIAL PRIMARY KEY, course_id INT NOT NULL, slug TEXT NOT NULL);
CREATE TABLE courses_submission (id SERIAL PRIMARY KEY, homework_id INT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL);
CREATE TABLE courses_registrationcampaign (id SERIAL PRIMARY KEY, slug TEXT NOT NULL);
CREATE TABLE courses_courseregistration (id SERIAL PRIMARY KEY, campaign_id INT NOT NULL,
    course_id INT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL);
INSERT INTO courses_course (id, slug) VALUES (1, 'mlops-zoomcamp'), (2, 'de-zoomcamp');
INSERT INTO courses_homework (id, course_id, slug) VALUES (10, 1, 'hw1'), (11, 1, 'hw2');
INSERT INTO courses_registrationcampaign (id, slug) VALUES (100, 'mlops-2026');
-- hw1: 2 first-submits on 10-20, 1 on 10-21
INSERT INTO courses_submission (homework_id, submitted_at) VALUES
  (10, '2026-10-20T10:00:00+00'), (10, '2026-10-20T12:00:00+00'),
  (10, '2026-10-21T09:00:00+00');
-- hw2: 1 row first submitted 10-20 then EDITED 10-21 (resubmit bumps submitted_at)
INSERT INTO courses_submission (homework_id, submitted_at) VALUES
  (11, '2026-10-21T15:00:00+00');
-- registrations: 2 approved + 1 pending on 10-20, one with NULL course (fallback)
INSERT INTO courses_courseregistration (campaign_id, course_id, status, created_at) VALUES
  (100, 1, 'approved', '2026-10-20T08:00:00+00'),
  (100, 1, 'approved', '2026-10-20T09:00:00+00'),
  (100, 1, 'pending', '2026-10-20T10:00:00+00'),
  (100, NULL, 'approved', '2026-10-20T11:00:00+00');
"""


def _rows_by_day_dims(rows):
    out = {}
    for day, dims, value in rows:
        if isinstance(dims, str):
            dims = json.loads(dims)
        out[(str(day), json.dumps(dims, sort_keys=True))] = int(value)
    return out


def test_homework_sql_counts_last_submit_day(pg):
    _exec(pg, FIXTURES)
    rows = _exec(
        pg,
        _read("cmp_homework_submissions.sql"),
        {"start": "2026-10-20", "end": "2026-10-22"},
    )
    got = _rows_by_day_dims(rows)
    hw1 = json.dumps({"course": "mlops-zoomcamp", "homework": "hw1"},
                     sort_keys=True)
    hw2 = json.dumps({"course": "mlops-zoomcamp", "homework": "hw2"},
                     sort_keys=True)
    # first submits land on their day
    assert got[("2026-10-20", hw1)] == 2
    assert got[("2026-10-21", hw1)] == 1
    # resubmitted row counts on the EDIT day only (bump verified in
    # homework_submission_for_user), not on first-submit day
    assert got[("2026-10-21", hw2)] == 1
    assert ("2026-10-20", hw2) not in got


def test_registrations_sql_splits_status_and_falls_back_to_campaign(pg):
    _exec(pg, FIXTURES)
    rows = _exec(
        pg,
        _read("cmp_course_registrations.sql"),
        {"start": "2026-10-20", "end": "2026-10-21"},
    )
    got = _rows_by_day_dims(rows)
    approved = json.dumps({"course": "mlops-zoomcamp", "status": "approved"},
                          sort_keys=True)
    pending = json.dumps({"course": "mlops-zoomcamp", "status": "pending"},
                         sort_keys=True)
    fallback = json.dumps({"course": "mlops-2026", "status": "approved"},
                          sort_keys=True)
    assert got[("2026-10-20", approved)] == 2
    assert got[("2026-10-20", pending)] == 1
    assert got[("2026-10-20", fallback)] == 1
    # every fixture row lands in exactly one series
    assert sum(got.values()) == 4


def test_website_registrations_sql_has_no_status(pg):
    _exec(pg, FIXTURES)
    rows = _exec(
        pg,
        _read("cmp_course_registrations_website.sql"),
        {"start": "2026-10-20", "end": "2026-10-21"},
    )
    got = _rows_by_day_dims(rows)
    plain = json.dumps({"course": "mlops-zoomcamp"}, sort_keys=True)
    fallback = json.dumps({"course": "mlops-2026"}, sort_keys=True)
    assert got[("2026-10-20", plain)] == 3
    assert got[("2026-10-20", fallback)] == 1
