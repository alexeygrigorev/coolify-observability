# biz-metrics — collect-only business metrics rollup (Phase 1, t1127u)

Nightly SQL rollup → Postgres `biz_metrics.metric_daily` (system of record)
→ VictoriaMetrics `/api/v1/import/prometheus` (live view in vmui).

Phase 1 is **collect-only**: this job writes rows and pushes gauges. It
contains no threshold logic and no alert rules. Alerts are deferred to
t1128u (Hub `ab72bb5b` — do NOT add vmalert rules or SQL checks here).

## Layout

```
biz-metrics/
  README.md                  this file
  schema.sql                 metric_daily DDL + roles (applied once by operator)
  sql/<product>/<metric>.sql one file per metric, returns (day, dims, value)
  sql/cmp/                   CMP + website course metrics (platform label)
  runner/rollup.py           stdlib + psycopg; upsert D-1..D-7; push to VM
  runner/requirements.txt
  cron/biz-metrics.cron      contabo-b cron line (Europe/Berlin 01:30)
  cron/biz-metrics.env.example
  tests/test_biz_metrics_cmp.py
```

## Data model

`metric_daily(day date, project text, metric text, dims jsonb,
value numeric, computed_at timestamptz,
PRIMARY KEY (day, project, metric, dims))`.

- `project` is the product family (`cmp` covers both platforms).
- `platform` (`cmp` | `website`) is a **dim from day one**, so series
  survive a course migration to the website. The runner tags rows by
  which source DSN the SQL ran against; the SQL files stay identical
  for both DBs except where schemas diverge (website
  `courses_courseregistration` has no `status` column).
- UTC calendar day grain. Recompute window D-1..D-7 every run (late
  submits and resubmit edits settle within days).

## Metrics (P0 CMP, t1127u)

| metric | source | dims |
|---|---|---|
| `cmp_homework_submissions` | `courses_submission.submitted_at` ⋈ homework ⋈ course | platform, course, homework |
| `cmp_course_registrations` | `courses_courseregistration.created_at` ⋈ course/campaign | platform, course, status (CMP only; website has no status column) |

`submitted_at` resubmit semantics (verified 2026-10-22 against
`courses/views/homework_submission.py` in both repos):
every submit — first or edit — sets `submitted_at = now()`. Scoring
does NOT touch it. So the metric counts rows by **last-submit day**;
an edited submission moves to the edit day. Backfill is stable only
after a homework closes. No `created_at` column exists on Submission,
so first-submit day is not recoverable — documented, not worked around.

Real Django table names (verified via `Model._meta.db_table`, = `\dt`):
CMP `courses_submission / courses_homework / courses_course /
courses_courseregistration (status, created_at) /
courses_registrationcampaign`; website `courses_submission /
courses_homework / courses_courseregistration (created_at, NO status) /
courses_registrationcampaign`, course dim = `courses_course` (Cohort).

## Run

```bash
pip install -r runner/requirements.txt
export BIZ_METRICS_STORE_DSN=... BIZ_METRICS_CMP_DSN=... \
       BIZ_METRICS_WEBSITE_DSN=... VM_PUSH_URL=http://10.100.0.1:8428/api/v1/import/prometheus
python3 runner/rollup.py --window 7                       # nightly: D-1..D-7
python3 runner/rollup.py --since 2024-01-01 --push        # backfill, then push
python3 runner/rollup.py --since 2026-10-21 --no-push --dry-run   # hand-check day
```

Hand-check one historic day against Studio/admin counts (prints rows, no writes):

```bash
python3 runner/rollup.py --since 2026-10-20 --until 2026-10-21 --no-push --dry-run
```

VM check: `biz_cmp_homework_submissions` / `biz_cmp_course_registrations`
in vmui for yesterday.

## Deploy checklist (operator, contabo-b)

1. `CREATE DATABASE biz_metrics` on pg-shared; apply `schema.sql`;
   `CREATE ROLE biz_ro` (+ `SELECT` on listed tables in `cmp`, `website`),
   `biz_rw` (write on `biz_metrics` only). Credentials live in the
   existing secrets path on contabo-b, never in this repo.
2. Add `biz_metrics` to the pg-shared nightly dump list.
3. Install cron + env; run backfill from earliest rows; confirm
   `metric_daily` rows, vmui yesterday values, and one hand-SQL match.
4. Confirm VM import is reachable over WG from contabo-b and whether
   `-dedup.minScrapeInterval` is set (re-pushing D-1..D-7 otherwise
   duplicates samples).
