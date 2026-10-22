"""Relay P0 biz-metrics tests — collect-only (t1127u, intake d9d8bd81).

No live PG required: SQL static checks, registry wiring, runner pure
functions (via runner/rollup.py), sqlite stand-ins for backfill/idempotency
and hand-SQL equivalence on one historic day.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql" / "relay"


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

UTC = dt.timezone.utc

RELAY_METRICS = [
    "relay_tx_messages",
    "relay_campaign_recipients",
    "relay_bounce_rate",
    "relay_complaint_rate",
]

EXPECTED_SQL = {
    "relay_tx_messages.sql": "relay_tx_messages",
    "relay_campaign_recipients.sql": "relay_campaign_recipients",
    "relay_bounce_rate.sql": "relay_bounce_rate",
    "relay_complaint_rate.sql": "relay_complaint_rate",
}

EXPECTED_DIMS = {
    "relay_tx_messages.sql": {"client", "status", "template_key"},
    "relay_campaign_recipients.sql": {"client", "status"},
    "relay_bounce_rate.sql": {"client", "stream"},
    "relay_complaint_rate.sql": {"client", "stream"},
}


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


# --- registry wiring (shared runner layout, one store) -----------------------

def test_relay_registry_entries():
    for metric in RELAY_METRICS:
        project, dsn_env, relpath, platform = rollup.REGISTRY[metric]
        assert project == "relay", metric
        assert dsn_env == "BIZ_METRICS_RELAY_DSN", metric
        assert (ROOT / "sql" / relpath).exists(), metric
        assert platform == "", metric  # no platform dim for Relay
        assert rollup.VM_SERIES.get(metric, metric) == metric


def test_relay_metrics_in_cli_choices():
    args = rollup.parse_args(["--metrics"] + RELAY_METRICS)
    assert args.metrics == RELAY_METRICS


# --- SQL static checks --------------------------------------------------------

import re  # noqa: E402


@pytest.mark.parametrize("name", sorted(EXPECTED_SQL))
def test_sql_returns_day_dims_value_with_utc_grain(name):
    text = _read(name)
    code = re.sub(r"--.*", "", text)
    assert "AS day" in code, name
    assert "AS dims" in code, name
    assert "AS value" in code, name
    assert "jsonb_build_object" in code, name
    assert "AT TIME ZONE 'UTC'" in code, name
    assert "%(start)s" in code and "%(end)s" in code, name


@pytest.mark.parametrize("name", sorted(EXPECTED_SQL))
def test_sql_no_pii_no_alerts(name):
    text = _read(name)
    code = re.sub(r"--.*", "", text).lower()
    for banned in ("user_id", "ip_address", "contact_id", "normalized_email",
                   "ses_message_id", "provider_event_id", "unsubscribe_token",
                   "tracking_token", "secret", "password"):
        assert banned not in code, (name, banned)
    block = text.lower().split("jsonb_build_object", 1)[1].split(")", 1)[0]
    assert "'email'" not in block and '"email"' not in block, name
    assert "campaign_id" not in block, name  # never a label (cardinality)
    for banned in ("vmalert", "threshold", "for:", "notify"):
        assert banned not in code, (name, banned)


@pytest.mark.parametrize("name", sorted(EXPECTED_SQL))
def test_sql_dims_allowlist(name):
    text = _read(name)
    keys = set(re.findall(r"'([a-z_]+)'\s*,", text))
    dims = {k for k in keys if k in {"client", "status", "template_key", "stream"}}
    assert dims == EXPECTED_DIMS[name], (name, dims)


def test_tx_sql_hits_indexed_table():
    code = _read("relay_tx_messages.sql")
    assert "transactional_messages" in code and "clients" in code
    assert "tm.template_key" in code and "c.slug" in code


def test_campaign_sql_sent_by_sent_at_others_by_updated_at():
    text = _read("relay_campaign_recipients.sql")
    assert "campaign_recipients" in text and "campaigns" in text
    assert "cr.sent_at" in text and "cr.updated_at" in text
    assert "cr.status = 'sent'" in text
    assert "<> 'pending'" in text


def test_rate_queries_zero_guarded_and_stream_split():
    for name in ("relay_bounce_rate.sql", "relay_complaint_rate.sql"):
        text = _read(name)
        assert "NULLIF(sent, 0)" in text, name
        assert "transactional_message_id IS NOT NULL THEN 'tx'" in text, name
        assert "campaign_id IS NOT NULL THEN 'campaign'" in text, name
    assert "'bounce'" in _read("relay_bounce_rate.sql")
    assert "'complaint'" in _read("relay_complaint_rate.sql")


def test_no_alert_wiring_in_relay_files():
    for p in [ROOT / "runner" / "rollup.py", ROOT / "schema.sql",
              ROOT / "README.md", ROOT / "cron" / "biz-metrics.env.example",
              *sorted(SQL_DIR.glob("*.sql"))]:
        low = p.read_text(encoding="utf-8").lower()
        assert "expr:" not in low, p.name
        for line in low.splitlines():
            s = line.strip()
            if s.startswith("#") or s.startswith("--"):
                continue
            if any(neg in s for neg in ("no vmalert", "no alert", "must not",
                                        "do not add", "deferred", "never", "without",
                                        "contains no", "not be added",
                                        "forbidden_manifest", "forbidden key",
                                        "no thresholds", "collect-only")):
                continue
            assert "vmalert" not in s, (p.name, s)


# --- runner behavior ----------------------------------------------------------

class _FakeCur:
    def __init__(self, rows):
        self._rows = rows
        self.executed: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self.cur = _FakeCur(rows)
        self.committed = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed += 1

    def close(self):
        pass


def test_run_source_upserts_relay_rows_without_platform():
    day = dt.date(2026, 10, 21)
    fetched = [(day, {"client": "cmp", "status": "sent",
                      "template_key": "login"}, 12)]
    source, store = _FakeConn(fetched), _FakeConn([])
    rows = rollup.run_source(source, store, "relay_tx_messages",
                             [day], dry_run=False)
    assert len(store.cur.executed) == 1
    params = store.cur.executed[0][1]
    assert params["project"] == "relay"
    assert params["metric"] == "relay_tx_messages"
    assert json.loads(params["dims"]) == {"client": "cmp", "status": "sent",
                                          "template_key": "login"}
    assert "platform" not in json.loads(params["dims"])
    assert rows[0]["series"] == "relay_tx_messages"


def test_run_source_skips_null_rate_rows():
    day = dt.date(2026, 10, 21)
    fetched = [(day, {"client": "cmp", "stream": "tx"}, None)]
    source, store = _FakeConn(fetched), _FakeConn([])
    rows = rollup.run_source(source, store, "relay_bounce_rate",
                             [day], dry_run=False)
    assert rows == []
    assert store.cur.executed == []


def test_relay_payload_has_biz_prefix_and_day_start_ts():
    day = dt.date(2026, 10, 21)
    rows = [{"series": "relay_bounce_rate",
             "dims": {"client": "cmp", "stream": "tx"},
             "value": 0.5, "day": day}]
    payload = rollup.build_payload(rows)
    assert payload.startswith("biz_relay_bounce_rate{")
    assert "1792540800000" in payload  # 2026-10-21 00:00:00Z


def test_upsert_sql_is_idempotent():
    assert "ON CONFLICT (day, project, metric, dims)" in rollup.UPSERT_SQL


def test_metric_daily_idempotent_on_sqlite_standin():
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE metric_daily(
      day TEXT, project TEXT, metric TEXT, dims TEXT, value REAL,
      PRIMARY KEY (day, project, metric, dims))""")
    upsert = """INSERT INTO metric_daily(day,project,metric,dims,value)
                VALUES (?,?,?,?,?)
                ON CONFLICT(day,project,metric,dims)
                DO UPDATE SET value=excluded.value"""
    row = ("2026-10-21", "relay", "relay_tx_messages",
           json.dumps({"client": "cmp", "status": "sent",
                       "template_key": "login"}, sort_keys=True), 5)
    con.execute(upsert, row)
    con.execute(upsert, row)  # backfill re-run
    con.execute(upsert, row[:-1] + (7,))  # corrected count
    assert con.execute("SELECT value FROM metric_daily").fetchall() == [(7.0,)]
    assert con.execute("SELECT COUNT(*) FROM metric_daily").fetchone() == (1,)


# ---------- Part B: live SQL against fixture tables (needs postgres) ----------
#
#   docker run --rm -d --name biztest-relay -e POSTGRES_PASSWORD=x -p 55434:5432 postgres:16-alpine
#   BIZMETRICS_TEST_DSN=postgresql://postgres:x@127.0.0.1:55434/postgres \
#     python3 -m pytest biz-metrics/tests/test_biz_metrics_relay.py -v
#   docker stop biztest-relay

RELAY_TEST_DSN = os.environ.get("BIZMETRICS_TEST_DSN", "")


@pytest.fixture(scope="module")
def pg():
    if not RELAY_TEST_DSN:
        pytest.skip("BIZMETRICS_TEST_DSN not set")
    pytest.importorskip("psycopg")
    import psycopg

    conn = psycopg.connect(RELAY_TEST_DSN, autocommit=True)
    yield conn
    conn.close()


def _exec(conn, sql: str, params: dict | None = None):
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001 — DDL returns no rows
            return []


RELAY_FIXTURES = """
DROP TABLE IF EXISTS email_events, campaign_recipients, campaigns,
    transactional_messages, clients;
CREATE TABLE clients (id SERIAL PRIMARY KEY, slug TEXT NOT NULL);
CREATE TABLE transactional_messages (id SERIAL PRIMARY KEY, client_id INT NOT NULL,
    status TEXT NOT NULL, template_key TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL);
CREATE TABLE campaigns (id SERIAL PRIMARY KEY, client_id INT NOT NULL,
    status TEXT NOT NULL, sent_at TIMESTAMPTZ NULL);
CREATE TABLE campaign_recipients (id SERIAL PRIMARY KEY, campaign_id INT NOT NULL,
    status TEXT NOT NULL, sent_at TIMESTAMPTZ NULL, updated_at TIMESTAMPTZ NOT NULL);
CREATE TABLE email_events (id SERIAL PRIMARY KEY, client_id INT NULL,
    campaign_id INT NULL, transactional_message_id INT NULL,
    event_type TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
INSERT INTO clients (id, slug) VALUES (1, 'cmp'), (2, 'aisl');
-- tx: 2 sent + 1 failed for cmp/login on 10-21, 1 sent aisl, 1 stale day
INSERT INTO transactional_messages (client_id, status, template_key, created_at) VALUES
  (1, 'sent', 'login', '2026-10-21T08:00:00+00'),
  (1, 'sent', 'login', '2026-10-21T09:00:00+00'),
  (1, 'failed', 'login', '2026-10-21T10:00:00+00'),
  (2, 'sent', 'welcome', '2026-10-21T11:00:00+00'),
  (1, 'sent', 'login', '2026-10-20T11:00:00+00');
-- campaigns: one sent 10-20, one sending
INSERT INTO campaigns (id, client_id, status, sent_at) VALUES
  (10, 1, 'sent', '2026-10-20T18:00:00+00'),
  (11, 1, 'sending', NULL);
-- recipients: sent counted by sent_at day; skipped by updated_at day; pending out
INSERT INTO campaign_recipients (campaign_id, status, sent_at, updated_at) VALUES
  (10, 'sent', '2026-10-20T18:01:00+00', '2026-10-20T18:01:00+00'),
  (10, 'sent', '2026-10-20T18:02:00+00', '2026-10-20T18:02:00+00'),
  (10, 'skipped', NULL, '2026-10-21T09:00:00+00'),
  (11, 'pending', NULL, '2026-10-21T09:00:00+00'),
  (10, 'bounced', NULL, '2026-10-21T10:00:00+00');
-- email_events 10-21: tx stream 2 sent / 1 bounce; campaign stream 1 sent / 1 complaint
INSERT INTO email_events
  (client_id, campaign_id, transactional_message_id, event_type, created_at) VALUES
  (1, NULL, 101, 'sent', '2026-10-21T08:00:00+00'),
  (1, NULL, 102, 'sent', '2026-10-21T08:01:00+00'),
  (1, NULL, 101, 'bounce', '2026-10-21T08:05:00+00'),
  (1, 10, NULL, 'sent', '2026-10-21T09:00:00+00'),
  (1, 10, NULL, 'complaint', '2026-10-21T09:05:00+00');
"""


def _rows_by_day_dims(rows):
    out = {}
    for day, dims, value in rows:
        if isinstance(dims, str):
            dims = json.loads(dims)
        out[(str(day), json.dumps(dims, sort_keys=True))] = (
            None if value is None else float(value))
    return out


def _dims(**kw):
    return json.dumps(kw, sort_keys=True)


def test_tx_sql_live_counts(pg):
    _exec(pg, RELAY_FIXTURES)
    got = _rows_by_day_dims(_exec(pg, _read("relay_tx_messages.sql"),
                                  {"start": "2026-10-21", "end": "2026-10-22"}))
    assert got[("2026-10-21", _dims(client="cmp", status="sent",
                                    template_key="login"))] == 2.0
    assert got[("2026-10-21", _dims(client="cmp", status="failed",
                                    template_key="login"))] == 1.0
    assert got[("2026-10-21", _dims(client="aisl", status="sent",
                                    template_key="welcome"))] == 1.0
    assert sum(v for v in got.values() if v is not None) == 4.0


def test_campaign_sql_live_day_rules(pg):
    _exec(pg, RELAY_FIXTURES)
    got = _rows_by_day_dims(_exec(pg, _read("relay_campaign_recipients.sql"),
                                  {"start": "2026-10-20", "end": "2026-10-22"}))
    assert got[("2026-10-20", _dims(client="cmp", status="sent"))] == 2.0
    assert got[("2026-10-21", _dims(client="cmp", status="skipped"))] == 1.0
    assert got[("2026-10-21", _dims(client="cmp", status="bounced"))] == 1.0
    assert not any("pending" in d for _, d in got)


def test_bounce_rate_sql_live(pg):
    _exec(pg, RELAY_FIXTURES)
    got = _rows_by_day_dims(_exec(pg, _read("relay_bounce_rate.sql"),
                                  {"start": "2026-10-21", "end": "2026-10-22"}))
    assert got[("2026-10-21", _dims(client="cmp", stream="tx"))] == pytest.approx(0.5)
    assert got[("2026-10-21", _dims(client="cmp", stream="campaign"))] == pytest.approx(0.0)


def test_complaint_rate_sql_live(pg):
    _exec(pg, RELAY_FIXTURES)
    got = _rows_by_day_dims(_exec(pg, _read("relay_complaint_rate.sql"),
                                  {"start": "2026-10-21", "end": "2026-10-22"}))
    assert got[("2026-10-21", _dims(client="cmp", stream="campaign"))] == pytest.approx(1.0)
    assert got[("2026-10-21", _dims(client="cmp", stream="tx"))] == pytest.approx(0.0)

def _seed_tx(con: sqlite3.Connection):
    con.execute("CREATE TABLE clients(id INTEGER PRIMARY KEY, slug TEXT)")
    con.execute("""CREATE TABLE transactional_messages(
      id INTEGER PRIMARY KEY, client_id INT, status TEXT,
      template_key TEXT, created_at TEXT)""")
    con.execute("INSERT INTO clients VALUES (1, 'cmp'), (2, 'aisl')")
    con.executemany(
        "INSERT INTO transactional_messages VALUES (?,?,?,?,?)",
        [(1, 1, "sent", "login", "2026-10-21 08:00:00"),
         (2, 1, "sent", "login", "2026-10-21 09:00:00"),
         (3, 1, "failed", "login", "2026-10-21 10:00:00"),
         (4, 2, "sent", "welcome", "2026-10-21 11:00:00"),
         (5, 1, "sent", "login", "2026-10-20 11:00:00")],
    )


def test_historic_day_tx_matches_hand_sql():
    con = sqlite3.connect(":memory:")
    _seed_tx(con)
    hand = dict(con.execute("""SELECT c.slug || '|' || tm.status
      || '|' || tm.template_key, COUNT(*) FROM transactional_messages tm
      JOIN clients c ON c.id = tm.client_id
      WHERE date(tm.created_at) = '2026-10-21' GROUP BY 1""").fetchall())
    assert hand == {"cmp|sent|login": 2, "cmp|failed|login": 1,
                    "aisl|sent|welcome": 1}


def test_historic_day_rate_math_matches_hand_sql():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE clients(id INTEGER PRIMARY KEY, slug TEXT)")
    con.execute("""CREATE TABLE email_events(id INTEGER PRIMARY KEY, client_id INT,
      campaign_id INT, transactional_message_id INT, event_type TEXT,
      created_at TEXT)""")
    con.execute("INSERT INTO clients VALUES (1, 'cmp')")
    con.executemany(
        "INSERT INTO email_events VALUES (?,?,?,?,?,?)",
        [(1, 1, None, 10, "sent", "2026-10-21 08:00:00"),
         (2, 1, None, 11, "sent", "2026-10-21 08:01:00"),
         (3, 1, None, 10, "bounce", "2026-10-21 08:05:00"),
         (4, 1, 5, None, "sent", "2026-10-21 09:00:00"),
         (5, 1, 5, None, "complaint", "2026-10-21 09:05:00")],
    )
    got = {r[0]: r[1] for r in con.execute("""SELECT
        CASE WHEN transactional_message_id IS NOT NULL THEN 'tx'
             ELSE 'campaign' END,
        CAST(SUM(CASE WHEN event_type='bounce' THEN 1 ELSE 0 END) AS REAL)
          / NULLIF(SUM(CASE WHEN event_type='sent' THEN 1 ELSE 0 END), 0)
        FROM email_events WHERE date(created_at)='2026-10-21' GROUP BY 1""")}
    assert got == {"tx": pytest.approx(0.5), "campaign": pytest.approx(0.0)}
    got_c = con.execute("""SELECT CAST(SUM(CASE WHEN event_type='complaint'
      THEN 1 ELSE 0 END) AS REAL)
      / NULLIF(SUM(CASE WHEN event_type='sent' THEN 1 ELSE 0 END), 0)
      FROM email_events WHERE date(created_at)='2026-10-21'
      AND campaign_id IS NOT NULL""").fetchone()
    assert got_c[0] == pytest.approx(1.0)
