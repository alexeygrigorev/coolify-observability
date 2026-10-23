"""Regression checks for deployment and recomputation, including real SQL."""
import datetime as dt
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rollup_live_contract', ROOT / 'runner/rollup.py')
rollup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollup)


def test_textfile_uses_latest_day_per_label_set(tmp_path):
    rows = [dict(series='m', dims={'course': 'c'}, day=dt.date(2026, 10, d), value=d)
            for d in [21, 20, 19]]
    text = Path(rollup.write_textfile(rows, str(tmp_path))).read_text()
    samples = [line for line in text.splitlines() if not line.startswith('#')]
    assert samples == ['biz_m{course="c"} 21']


def test_payload_deduplicates_weekly_samples():
    row = dict(series='m', dims={'grain': 'week'}, day=dt.date(2026, 10, 19), value=4)
    assert rollup.build_payload([row, row]) == 'biz_m{grain="week"} 4 1792368000000\n'


def test_error_does_not_print_configuration():
    import subprocess
    import sys
    env = {**os.environ, 'BIZ_METRICS_STORE_DSN': 'not-a-valid-dsn-private-marker'}
    result = subprocess.run([sys.executable, str(ROOT / 'runner/rollup.py')],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'private-marker' not in result.stderr
    assert 'rollup failed (' in result.stderr


def test_recompute_replaces_vanished_dimensions_and_preserves_other_platform():
    dsn = os.environ.get('BIZMETRICS_TEST_DSN')
    if not dsn:
        pytest.skip('BIZMETRICS_TEST_DSN not set')
    psycopg = pytest.importorskip('psycopg')
    # Dedicated test DB only. All DDL and rows roll back with the transaction.
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute('CREATE SCHEMA live_contract')
            cur.execute('SET LOCAL search_path TO live_contract')
            cur.execute((ROOT / 'schema.sql').read_text())
            cur.execute('CREATE TABLE courses_course (id int, slug text)')
            cur.execute('CREATE TABLE courses_homework (id int, course_id int, slug text)')
            cur.execute('CREATE TABLE courses_submission (homework_id int, submitted_at timestamptz)')
            cur.execute("INSERT INTO courses_course VALUES (1, 'course')")
            cur.execute("INSERT INTO courses_homework VALUES (1, 1, 'hw')")
            cur.execute("INSERT INTO courses_submission VALUES (1, '2026-10-20 12:00+00')")
        day = dt.date(2026, 10, 20)
        rollup.run_source(conn, conn, 'cmp_homework_submissions_website', [day], False)
        rollup.run_source(conn, conn, 'cmp_homework_submissions', [day], False)
        with conn.cursor() as cur:
            cur.execute("UPDATE courses_submission SET submitted_at='2026-10-21 12:00+00'")
        for _ in range(2):
            rollup.run_source(conn, conn, 'cmp_homework_submissions', [day, day + dt.timedelta(days=1)], False)
        with conn.cursor() as cur:
            cur.execute("SELECT day, dims->>'platform', value FROM metric_daily ORDER BY day")
            assert cur.fetchall() == [(day, 'website', 1), (day + dt.timedelta(days=1), 'cmp', 1)]
        conn.rollback()
