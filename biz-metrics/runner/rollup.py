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
  BIZ_METRICS_RELAY_DSN    psycopg DSN for the Relay app DB (read role biz_ro)
  VM_PUSH_URL              e.g. http://10.100.0.1:8428/api/v1/import/prometheus
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
}

# VM series keep the catalog metric names (no _website suffix); platform
# disambiguates.
VM_SERIES = {
    "cmp_homework_submissions_website": "cmp_homework_submissions",
    "cmp_course_registrations_website": "cmp_course_registrations",
}

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
    """One Prometheus text line with an explicit day-start-UTC timestamp (ms)."""
    labels = "".join(
        f', {k}="{prom_escape(str(v))}"' for k, v in sorted(dims.items())
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
    return "\n".join(
        render_sample(r["series"], r["dims"], r["value"], r["day"])
        for r in sorted(
            rows,
            key=lambda r: (
                str(r["day"]),
                r["series"],
                json.dumps(r["dims"], sort_keys=True),
            ),
        )
    ) + "\n"


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
        for row_day, dims, value in fetched:
            if isinstance(dims, str):
                dims = json.loads(dims)
            if value is None:
                continue  # NULL rate (zero-send window): nothing to store/push
            dims = dict(dims)
            if platform:
                dims = {"platform": platform, **dims}
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
    return ap.parse_args(argv)


def resolve_days(args: argparse.Namespace) -> list[dt.date]:
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
        psycopg.connect(store_dsn) if not args.dry_run else None
    )
    try:
        for metric in args.metrics:
            _, dsn_env, _, _ = REGISTRY[metric]
            source_dsn = os.environ.get(dsn_env, "")
            if not source_dsn:
                print(f"skip {metric}: {dsn_env} not set", file=sys.stderr)
                continue
            with psycopg.connect(source_dsn) as source_conn:
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
    if args.dry_run or not args.push:
        sys.stdout.write(payload)
        return 0
    if not vm_url:
        print("VM_PUSH_URL is required for --push", file=sys.stderr)
        return 2
    status, body = push_vm(vm_url, payload)
    print(f"pushed {len(all_rows)} samples -> {status} {body[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
