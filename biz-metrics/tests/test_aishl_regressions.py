"""Execute AISHL SQL against PostgreSQL to check privacy and day boundaries."""

import datetime as dt

import pytest

from test_biz_metrics_aishl import (
    AISHL_METRICS,
    _run_day,
    pg_dsn,
    rollup,
    seeded_dsn,
)


@pytest.fixture
def conn(seeded_dsn):
    import psycopg

    connection = psycopg.connect(seeded_dsn)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize("metric", AISHL_METRICS)
def test_empty_day_has_a_daily_zero(conn, metric):
    rows = _run_day(conn, metric, dt.date(2024, 1, 2))
    daily = []
    for day, dims, value in rows:
        if dims.get("grain") != "week":
            daily.append((day, value))
    assert daily == [("2024-01-02", 0)]


@pytest.mark.parametrize("metric", [
    "aishl_signups", "aishl_paid_conversions", "aishl_new_mrr_eur",
])
def test_untrusted_source_values_never_reach_labels(conn, metric):
    sources = ["person@example.invalid", "192.0.2.1", "private-person-name"]
    with conn.cursor() as cur:
        for user_id, source in enumerate(sources, 100):
            cur.execute("INSERT INTO analytics_useractivity "
                        "(user_id,event_type,occurred_at) VALUES (%s,'signup',%s)",
                        (user_id, "2026-10-22T12:00:00Z"))
            cur.execute("INSERT INTO analytics_userattribution VALUES (%s,%s)",
                        (user_id, source))
            cur.execute("INSERT INTO payments_conversionattribution "
                        "(first_touch_utm_source,mrr_eur,created_at) VALUES (%s,7,%s)",
                        (source, "2026-10-22T12:00:00Z"))
    rows = _run_day(conn, metric, dt.date(2026, 10, 22))
    assert len(rows) == 1
    assert rows[0][1]["utm_source"] == "other"
    expected = 3
    if metric == "aishl_new_mrr_eur":
        expected = 21
    assert rows[0][2] == expected
    payload = rollup.build_payload([
        {"series": metric, "day": dt.date(2026, 10, 22),
         "dims": rows[0][1], "value": rows[0][2]},
    ])
    for source in sources:
        assert source not in payload


@pytest.mark.parametrize("metric", ["aishl_paid_conversions", "aishl_new_mrr_eur"])
def test_invalid_billing_period_is_bucketed(conn, metric):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO payments_conversionattribution "
                    "(billing_period,mrr_eur,created_at) VALUES (%s,7,%s)",
                    ("person@example.invalid", "2026-10-22T12:00:00Z"))
    rows = _run_day(conn, metric, dt.date(2026, 10, 22))
    assert rows[0][1]["billing_period"] == "other"


@pytest.mark.parametrize("metric", ["aishl_lesson_opens", "aishl_active_learners"])
def test_oversized_object_id_is_unknown(conn, metric):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO analytics_useractivity "
                    "(user_id,event_type,occurred_at,object_type,object_id) "
                    "VALUES (100,'lesson_open',%s,'unit',%s)",
                    ("2026-10-22T12:00:00Z", "9" * 200))
    rows = _run_day(conn, metric, dt.date(2026, 10, 22))
    unknown = []
    for day, dims, value in rows:
        if dims.get("course") == "unknown":
            unknown.append((day, value))
    assert unknown == [("2026-10-22", 1)]


@pytest.mark.parametrize("zone", ["Pacific/Auckland", "America/Los_Angeles", "Europe/Berlin"])
def test_week_bounds_are_utc_even_across_dst(conn, zone):
    with conn.cursor() as cur:
        for user_id, timestamp in [(100, "2026-10-25T23:30:00Z"),
                                   (101, "2026-10-26T00:00:00Z")]:
            cur.execute("INSERT INTO analytics_useractivity "
                        "(user_id,event_type,occurred_at) VALUES (%s,'resource_view',%s)",
                        (user_id, timestamp))
        cur.execute("SET TIME ZONE 'UTC'")
        expected = _run_day(conn, "aishl_active_learners", dt.date(2026, 10, 25))
        cur.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
        actual = _run_day(conn, "aishl_active_learners", dt.date(2026, 10, 25))
    assert actual == expected
    assert ("2026-10-19", {"course": "all", "grain": "week"}, 8) in actual
    assert ("2026-10-25", {"course": "all", "grain": "day"}, 1) in actual


def test_historic_fixture_totals_match_independent_sql(conn):
    start, end = "2026-10-20T00:00:00Z", "2026-10-21T00:00:00Z"
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FILTER (WHERE event_type='lesson_open'), "
                    "count(DISTINCT user_id) FILTER "
                    "(WHERE event_type IN ('lesson_open','resource_view')), "
                    "count(*) FILTER (WHERE event_type='signup') "
                    "FROM analytics_useractivity "
                    "WHERE occurred_at >= %s AND occurred_at < %s", (start, end))
        expected = list(cur.fetchone())
        cur.execute("SELECT count(*), coalesce(sum(mrr_eur),0) "
                    "FROM payments_conversionattribution "
                    "WHERE created_at >= %s AND created_at < %s", (start, end))
        expected.extend(cur.fetchone())
    actual = []
    for metric in AISHL_METRICS:
        rows = _run_day(conn, metric, dt.date(2026, 10, 20))
        total = 0
        for _, dims, value in rows:
            if metric == "aishl_active_learners":
                if dims != {"course": "all", "grain": "day"}:
                    continue
            total += value
        actual.append(total)
    assert actual == expected == [5, 5, 3, 3, 54]
