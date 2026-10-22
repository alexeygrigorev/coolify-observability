# biz-metrics — collect-only business metrics rollup (Phase 1, t1127u)

Nightly SQL rollup → Postgres `biz_metrics.metric_daily` (system of record)
→ VictoriaMetrics `/api/v1/import/prometheus` (live view in vmui).

Phase 1 is **collect-only**: this job writes rows and pushes gauges. It
contains no threshold logic and no alert rules. Alerts are deferred to
t1128u (Hub `ab72bb5b` — do NOT add vmalert rules or SQL checks here).

Plumbing intake: `6d564162`
([hub](https://hub.dtcdev.click/#/intake/6d564162-fe6a-497f-afc9-4cd78842e6ba)) ·
Parent: `de12a818` · Catalog §1 + §4 Intake A.

## Layout

```
biz-metrics/
  README.md                  this file
  schema.sql                 metric_daily DDL + role grants (applied once by operator)
  roles.sql                  least-privilege grants per DB (biz_ro SELECT, biz_rw write)
  sql/<product>/<metric>.sql one file per metric, returns (day, dims, value)
  sql/cmp/                   CMP + website course metrics (platform label)
  sql/_template.sql          contract for new metrics (product intakes copy it)
  runner/rollup.py           stdlib + psycopg; upsert D-1..D-7; push to VM
  runner/requirements.txt
  cron/biz-metrics.cron      contabo-b cron (Europe/Berlin 01:30 + optional hourly)
  cron/biz-metrics.env.example
  sql/relay/                 Relay P0 metrics (tx/campaign/bounce/complaint)
  cron/run.sh                cron wrapper (sources /data/biz-metrics/env)
  install-biz-metrics.sh     operator installer (copies files, cron, env stub)
  check-dump.sh              verifies pg-shared dump list includes biz_metrics
  tests/test_biz_metrics_cmp.py       CMP P0 tests (live PG fixtures optional)
  tests/test_biz_metrics_relay.py     Relay P0 tests (live PG fixtures optional)
  tests/test_biz_metrics_plumbing.py  plumbing tests (no DB, no secrets)
```

## Data model

`metric_daily(day date, project text, metric text, dims jsonb,
value numeric, computed_at timestamptz,
PRIMARY KEY (day, project, metric, dims))`.

- `project` is the product family (`relay`, `cmp` — `cmp` covers both platforms).
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

Product metric intakes: Relay `d9d8bd81` (`sql/relay/`,
`BIZ_METRICS_RELAY_DSN` on pg-relay), CMP `6987cdae`, AISHL `8cc61eb4`.
Each file returns `(day, dims, value)` binding `%(start)s`/`%(end)s`.

## Run

```bash
pip install -r runner/requirements.txt
export BIZ_METRICS_STORE_DSN=... BIZ_METRICS_CMP_DSN=... \
       BIZ_METRICS_WEBSITE_DSN=... BIZ_METRICS_RELAY_DSN=... VM_PUSH_URL=http://10.100.0.1:8428/api/v1/import/prometheus
python3 runner/rollup.py --window 7                       # nightly: D-1..D-7
python3 runner/rollup.py --since 2024-01-01 --push        # backfill, then push
python3 runner/rollup.py --since 2026-10-21 --no-push --dry-run   # hand-check day
```

Hand-check one historic day against Studio/admin counts (prints rows, no writes):

```bash
python3 runner/rollup.py --since 2026-10-20 --until 2026-10-21 --no-push --dry-run
```

Hourly today-so-far illuminator for vmui (partial UTC day; durable history
still comes from the nightly run):

```bash
python3 runner/rollup.py --today-so-far
```

VM check: `biz_cmp_homework_submissions` / `biz_cmp_course_registrations`
in vmui for yesterday.

## Metrics (P0 Relay, t1127u — intake d9d8bd81, parent de12a818)

| metric | source (pg-relay / DB relay) | dims | VM series |
|---|---|---|---|
| `relay_tx_messages` | `transactional_messages.created_at` ⋈ `clients` | client, status, template_key | `biz_relay_tx_messages` |
| `relay_campaign_recipients` | `campaign_recipients` ⋈ `campaigns.client_id` ⋈ `clients` | client, status | `biz_relay_campaign_recipients` |
| `relay_bounce_rate` | `email_events` sent vs bounce | client, stream=tx\|campaign | `biz_relay_bounce_rate` |
| `relay_complaint_rate` | `email_events` sent vs complaint | client, stream=tx\|campaign | `biz_relay_complaint_rate` |

- `sent` campaign recipients count by `sent_at` day; every other terminal
  status by `updated_at` day. `pending` excluded.
- Stream: `tx` iff `transactional_message_id IS NOT NULL`, `campaign` iff
  `campaign_id IS NOT NULL`. `NULL` rate on zero-send days is skipped
  (nothing stored/pushed).
- No PII labels: never email, user_id, IP, contact, or `campaign_id`.
  Table names verified against `relay/mailing/models.py` (`db_table`).

Run with Relay: add `BIZ_METRICS_RELAY_DSN=...` to the env from
`cron/biz-metrics.env.example`; the runner picks up `--metrics
relay_tx_messages relay_campaign_recipients relay_bounce_rate
relay_complaint_rate` (default = all registered metrics).

Hand-check one historic day (pg-relay):

```bash
psql "$BIZ_METRICS_RELAY_DSN" -c "SELECT status, COUNT(*) FROM transactional_messages
  WHERE created_at >= '2026-10-20+00' AND created_at < '2026-10-21+00' GROUP BY 1;"
psql "$BIZ_METRICS_STORE_DSN" -c "SELECT dims, value FROM metric_daily
  WHERE day='2026-10-20' AND project='relay' AND metric='relay_tx_messages';"
```

## Deploy checklist (operator, contabo-b)

1. `CREATE DATABASE biz_metrics` on pg-shared; apply `schema.sql`;
   `CREATE ROLE biz_ro` (+ `SELECT` on listed tables in `cmp`, `website`,
   and on pg-relay / DB `relay`), `biz_rw` (write on `biz_metrics` only). Full
   grants in `roles.sql`. Credentials live in the existing secrets path on
   contabo-b, never in this repo.
2. Add `biz_metrics` to the pg-shared nightly dump list
   (`PG_SHARED_DBS="cmp aisl website biz_metrics"` in
   `/etc/coolify-pg-dump.env`); verify with `./biz-metrics/check-dump.sh`.
3. Install: `./biz-metrics/install-biz-metrics.sh contabo-b`
   (copies `runner/`+`sql/` to `/data/biz-metrics`, wrapper to
   `/data/biz-metrics/run.sh`, cron fragment, env stub); fill
   `/data/biz-metrics/env` (mode 600); run backfill from earliest rows;
   confirm `metric_daily` rows, vmui yesterday values, and one hand-SQL match.
4. Confirm VM import is reachable over WG from contabo-b and whether
   `-dedup.minScrapeInterval` is set (re-pushing D-1..D-7 otherwise
   duplicates samples).

## Textfile fallback

If `POST /api/v1/import/prometheus` is rejected from contabo-b, run with
`--textfile-dir <node_exporter textfile dir>`; the runner writes
`biz_metrics.prom` (gauges, no timestamps — textfile format has none).
Confirm the `:9100` collector runs with `--collector.textfile.directory` set
(already scraped per `configs/vm/prometheus.yml`); yesterday series then appear
via the normal `node` scrape job instead of the import endpoint.

## Tests

```bash
python3 -m pytest biz-metrics/tests/ -v          # plumbing (no DB, no docker)
BIZMETRICS_TEST_DSN=... python3 -m pytest biz-metrics/tests/test_biz_metrics_cmp.py -v  # + live PG
```
