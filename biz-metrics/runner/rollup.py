"""biz-metrics rollup runner — Phase 1 collect-only (t1127u).

Reads sql/<product>/<metric>.sql files (each returns day, dims, value),
upserts D-1..D-7 (or a --since/--until backfill range) into
biz_metrics.metric_daily, and pushes the day's values to VictoriaMetrics
/api/v1/import/prometheus with explicit day-start-UTC timestamps.

Collect-only: no thresholds, no alerts. stdlib + psycopg (see requirements).

Env:
  BIZ_METRICS_STORE_DSN    psycopg DSN for biz_metrics (write role biz_rw)
  BIZ_METRICS_CMP_DSN      psycopg DSN for the CMP app DB (read role biz_ro)
  BIZ_METRICS_WEBSITE_DSN  psycopg DSN for the website app DB (read role biz_ro)
  BIZ_METRICS_RELAY_DSN    psycopg DSN for the Relay app DB on pg-relay (read role biz_ro)
  BIZ_METRICS_AISHL_DSN    psycopg DSN for the aisl app DB (read role biz_ro)
  VM_PUSH_URL              e.g. http://10.100.0.1:8428/api/v1/import/prometheus

Registry entries name their source DSN env; product intakes (relay, AISHL)
append entries with their own DSN envs. --today-so-far upserts only today
(hourly vmui illuminator). --textfile-dir writes a node_exporter fallback.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SQL_ROOT = os.path.normpath(os.path.join(HERE, "..", "sql"))

# Never push these as VM labels (PII / unbounded cardinality). Dropped
# defensively at render time; SQL files must not select them either.
BLOCKED_LABELS = frozenset(
    {
        "email",
        "e-mail",
        "user_id",
        "userid",
        "user-id",
        "student_id",
        "ip",
        "ip_address",
        "phone",
        "token",
    }
)

MAX_LABEL_VALUE_LEN = 128

# metric -> (project, source dsn env, sql file, platform).
# platform is tagged by the runner from day one; the same SQL file serves
# both DBs wherever schemas match.
REGISTRY = {
    "cmp_homework_submissions": (
        "cmp",
        "BIZ_METRICS_CMP_DSN",
        os.path.join("cmp", "cmp_homework_submissions.sql"),
        "cmp",
    ),
    "cmp_homework_submissions_website": (
        "cmp",
        "BIZ_METRICS_WEBSITE_DSN",
        os.path.join("cmp", "cmp_homework_submissions.sql"),
        "website",
    ),
    "cmp_course_registrations": (
        "cmp",
        "BIZ_METRICS_CMP_DSN",
        os.path.join("cmp", "cmp_course_registrations.sql"),
        "cmp",
    ),
    "cmp_course_registrations_website": (
        "cmp",
        "BIZ_METRICS_WEBSITE_DSN",
        os.path.join("cmp", "cmp_course_registrations_website.sql"),
        "website",
    ),
    # Relay P0 (t1127u, intake d9d8bd81): no platform dim; dims carry
    # client/status/template_key/stream. Empty platform disables injection.
    "relay_tx_messages": (
        "relay",
        "BIZ_METRICS_RELAY_DSN",
        os.path.join("relay", "relay_tx_messages.sql"),
        "",
    ),
    "relay_campaign_recipients": (
        "relay",
        "BIZ_METRICS_RELAY_DSN",
        os.path.join("relay", "relay_campaign_recipients.sql"),
        "",
    ),
    "relay_bounce_rate": (
        "relay",
        "BIZ_METRICS_RELAY_DSN",
        os.path.join("relay", "relay_bounce_rate.sql"),
        "",
    ),
    "relay_complaint_rate": (
        "relay",
        "BIZ_METRICS_RELAY_DSN",
        os.path.join("relay", "relay_complaint_rate.sql"),
        "",
    ),
    # AISHL P0 (t1127u-D, intake 8cc61eb4): single app DB (aisl), so empty
    # platform disables injection -- the SQL dims are the full label set.
    "aishl_lesson_opens": (
        "aishl",
        "BIZ_METRICS_AISHL_DSN",
        os.path.join("aishl", "aishl_lesson_opens.sql"),
        "",
    ),
    "aishl_active_learners": (
        "aishl",
        "BIZ_METRICS_AISHL_DSN",
        os.path.join("aishl", "aishl_active_learners.sql"),
        "",
    ),
    "aishl_signups": (
        "aishl",
        "BIZ_METRICS_AISHL_DSN",
        os.path.join("aishl", "aishl_signups.sql"),
        "",
    ),
    "aishl_paid_conversions": (
        "aishl",
        "BIZ_METRICS_AISHL_DSN",
        os.path.join("aishl", "aishl_paid_conversions.sql"),
        "",
    ),
    "aishl_new_mrr_eur": (
        "aishl",
        "BIZ_METRICS_AISHL_DSN",
        os.path.join("aishl", "aishl_new_mrr_eur.sql"),
        "",
    ),
}

# VM series keep the catalog metric names (no _website suffix); platform
# disambiguates.
VM_SERIES = {
    "cmp_homework_submissions_website": "cmp_homework_submissions",
    "cmp_course_registrations_website": "cmp_course_registrations",
}

DELETE_DAY_SQL = """DELETE FROM metric_daily
WHERE day = %(day)s AND project = %(project)s AND metric = %(metric)s
  AND (%(platform)s = '' OR dims->>'platform' = %(platform)s)"""

UPSERT_SQL = """INSERT INTO metric_daily (day, project, metric, dims, value, computed_at)
VALUES (%(day)s, %(project)s, %(metric)s, %(dims)s::jsonb, %(value)s, now())
ON CONFLICT (day, project, metric, dims)
DO UPDATE SET value = EXCLUDED.value, computed_at = now()"""


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def window_days(window: int, today: dt.date | None = None) -> list[dt.date]:
    """Nightly recompute window: D-1 .. D-window (default 7)."""
    today = today or utc_today()
    return [today - dt.timedelta(days=d) for d in range(1, window + 1)]


def day_bounds(day: dt.date) -> tuple[str, str]:
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def load_sql(relpath: str) -> str:
    with open(os.path.join(SQL_ROOT, relpath), encoding="utf-8") as fh:
        return fh.read()


def prom_escape(value: str) -> str:
    return value.replace("\\", r"\\").replace('"', r"\"").replace("\n", r"\n")


def render_sample(
    series: str, dims: dict, value: object, day: dt.date
) -> str:
    """One Prometheus text line with an explicit day-start-UTC timestamp (ms).

    Blocked (PII/unbounded) label keys are dropped, never pushed.
    """
    kept = {
        k: v for k, v in dims.items()
        if k.strip().lower() not in BLOCKED_LABELS
    }
    labels = "".join(
        f', {k}="{prom_escape(str(v)[:MAX_LABEL_VALUE_LEN])}"'
        for k, v in sorted(kept.items())
    )
    if labels.startswith(", "):
        labels = labels[2:]
    ts = int(
        dt.datetime(
            day.year, day.month, day.day, tzinfo=dt.timezone.utc
        ).timestamp()
        * 1000
    )
    return f"biz_{series}{{{labels}}} {value} {ts}"


def build_payload(rows: list[dict]) -> str:
    """rows: [{series, dims, value, day}]. One line per row, sorted for goldens."""
    # Weekly queries can return the same Monday sample for several days.
    unique = {(r["series"], json.dumps(r["dims"], sort_keys=True), r["day"]): r
              for r in rows}
    return "\n".join(
        render_sample(r["series"], r["dims"], r["value"], r["day"])
        for r in sorted(
            unique.values(),
            key=lambda r: (
                str(r["day"]),
                r["series"],
                json.dumps(r["dims"], sort_keys=True),
            ),
        )
    ) + ("\n" if unique else "")


def push_vm(url: str, payload: str, timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=payload.encode("utf-8"), method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (operator URL)
        return resp.status, resp.read().decode("utf-8", "replace")


def run_source(
    source_conn, store_conn, metric: str, days: list[dt.date], dry_run: bool
) -> list[dict]:
    """Query one registry entry for the day list; upsert; return VM rows."""
    project, _, relpath, platform = REGISTRY[metric]
    series = VM_SERIES.get(metric, metric)
    sql = load_sql(relpath)
    vm_rows: list[dict] = []
    for day in days:
        start, end = day_bounds(day)
        with source_conn.cursor() as cur:
            cur.execute(sql, {"start": start, "end": end})
            fetched = cur.fetchall()
        # Replace this source's daily slice in the same store transaction.
        # A resubmit or status change can remove a dimension entirely.
        if not dry_run:
            with store_conn.cursor() as cur:
                cur.execute(DELETE_DAY_SQL, {
                    "day": day, "project": project,
                    "metric": series, "platform": platform,
                })
        for row_day, dims, value in fetched:
            if isinstance(dims, str):
                dims = json.loads(dims)
            if value is None:
                continue  # NULL rate (zero-send window): nothing to store/push
            dims = dict(dims)
            if platform:
                dims = {**dims, "platform": platform}
            if not dry_run:
                with store_conn.cursor() as cur:
                    cur.execute(
                        UPSERT_SQL,
                        {
                            "day": row_day,
                            "project": project,
                            "metric": series,
                            "dims": json.dumps(dims, sort_keys=True),
                            "value": value,
                        },
                    )
            vm_rows.append(
                {"series": series, "dims": dims, "value": value, "day": row_day}
            )
    return vm_rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", type=int, default=7,
                    help="recompute D-1..D-window (default 7)")
    ap.add_argument("--since", default=None, help="backfill start (YYYY-MM-DD)")
    ap.add_argument("--until", default=None,
                    help="backfill end exclusive (YYYY-MM-DD, default today UTC)")
    ap.add_argument("--metrics", nargs="*", default=sorted(REGISTRY),
                    choices=sorted(REGISTRY))
    ap.add_argument("--push", dest="push", action="store_true", default=True)
    ap.add_argument("--no-push", dest="push", action="store_false")
    ap.add_argument("--dry-run", action="store_true",
                    help="query sources and print payload; no writes, no push")
    ap.add_argument("--today-so-far", action="store_true",
                    help="upsert only today (UTC); hourly vmui illuminator")
    ap.add_argument("--textfile-dir", default=None,
                    help="also write node_exporter textfile fallback here")
    return ap.parse_args(argv)


def write_textfile(rows: list[dict], textfile_dir: str) -> str:
    """node_exporter textfile fallback (gauges; textfile format has no
    timestamps, so this carries the latest pushed values)."""
    os.makedirs(textfile_dir, exist_ok=True)
    out = os.path.join(textfile_dir, "biz_metrics.prom")
    tmp = out + ".tmp"
    names = sorted({f"biz_{r['series']}" for r in rows})
    # Textfile scraping has no historic timestamps: retain only the latest
    # day for each series/label set, avoiding duplicate Prometheus samples.
    latest = {}
    for row in rows:
        key = (row["series"], json.dumps(row["dims"], sort_keys=True))
        if key not in latest or row["day"] > latest[key]["day"]:
            latest[key] = row
    rows = list(latest.values())
    with open(tmp, "w", encoding="utf-8") as fh:
        for name in names:
            fh.write(f"# HELP {name} business daily aggregate (collect-only)\n")
            fh.write(f"# TYPE {name} gauge\n")
        for r in sorted(rows, key=lambda r: (
                r["series"], json.dumps(r["dims"], sort_keys=True),
                str(r["day"]))):
            labels = "".join(
                f', {k}="{prom_escape(str(v)[:MAX_LABEL_VALUE_LEN])}"'
                for k, v in sorted(r["dims"].items())
                if k.strip().lower() not in BLOCKED_LABELS
            )
            if labels.startswith(", "):
                labels = labels[2:]
            fh.write(f"biz_{r['series']}{{{labels}}} {r['value']}\n")
    os.replace(tmp, out)
    return out


def resolve_days(args: argparse.Namespace) -> list[dt.date]:
    if args.today_so_far:
        return [utc_today()]
    if args.since:
        since = dt.date.fromisoformat(args.since)
        until = (
            dt.date.fromisoformat(args.until)
            if args.until
            else utc_today()
        )
        days: list[dt.date] = []
        d = since
        while d < until:
            days.append(d)
            d += dt.timedelta(days=1)
        return days
    return window_days(args.window)


def connect_database(psycopg, env_name: str):
    # The root wrapper resolves Coolify container addresses each run. No DB
    # port is published and container restarts cannot leave stale IPs here.
    host_key = ("BIZ_METRICS_RELAY_HOSTADDR" if env_name == "BIZ_METRICS_RELAY_DSN"
                else "BIZ_METRICS_SHARED_HOSTADDR")
    options = {"connect_timeout": 15, "options": "-c timezone=UTC -c statement_timeout=120000"}
    if os.environ.get(host_key):
        options["hostaddr"] = os.environ[host_key]
    return psycopg.connect(os.environ[env_name], **options)


def main(argv: list[str] | None = None) -> int:
    import psycopg  # runtime dep on contabo-b; tests stub pure functions

    args = parse_args(argv)
    days = resolve_days(args)
    store_dsn = os.environ.get("BIZ_METRICS_STORE_DSN", "")
    vm_url = os.environ.get("VM_PUSH_URL", "")
    if not args.dry_run and not store_dsn:
        print("BIZ_METRICS_STORE_DSN is required (unless --dry-run)",
              file=sys.stderr)
        return 2

    all_rows: list[dict] = []
    store_conn = (
        connect_database(psycopg, "BIZ_METRICS_STORE_DSN") if not args.dry_run else None
    )
    try:
        for metric in args.metrics:
            _, dsn_env, _, _ = REGISTRY[metric]
            source_dsn = os.environ.get(dsn_env, "")
            if not source_dsn:
                print(f"skip {metric}: {dsn_env} not set", file=sys.stderr)
                continue
            with connect_database(psycopg, dsn_env) as source_conn:
                rows = run_source(
                    source_conn, store_conn, metric, days, args.dry_run
                )
            all_rows.extend(rows)
        if store_conn is not None:
            store_conn.commit()
    finally:
        if store_conn is not None:
            store_conn.close()

    payload = build_payload(all_rows)
    if args.textfile_dir:
        out = write_textfile(all_rows, args.textfile_dir)
        print(f"textfile fallback: {out}")
    if args.dry_run or not args.push:
        sys.stdout.write(payload)
        return 0
    if not vm_url:
        print("VM_PUSH_URL is required for --push", file=sys.stderr)
        return 2
    status, _body = push_vm(vm_url, payload)
    print(f"pushed {len(payload.splitlines())} samples; HTTP {status}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Driver/HTTP errors can include DSNs, credentials or endpoint URLs.
        print(f"rollup failed ({type(exc).__name__}); check private configuration",
              file=sys.stderr)
        raise SystemExit(1) from None
