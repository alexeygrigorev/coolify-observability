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
  sql/aishl/                 AISHL P0 metrics (lesson/signup/paid+MRR, t1127u-D)
  cron/run.sh                cron wrapper (sources /etc/biz-metrics.env)
  install-biz-metrics.sh     operator installer (venv, cron, private env stub)
  provision-biz-metrics.py   node-only DB/role provisioning; credentials stay in /etc
  check-dump.sh              verifies pg-shared dump list includes biz_metrics
  tests/test_biz_metrics_cmp.py       CMP P0 tests (live PG fixtures optional)
  tests/test_biz_metrics_relay.py     Relay P0 tests (live PG fixtures optional)
  tests/test_biz_metrics_aishl.py     AISHL P0 tests (live PG fixtures optional)
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

## Metrics (P0 AISHL, t1127u-D — intake 8cc61eb4, parent de12a818)

| metric | source (pg-shared / DB aisl) | dims | VM series |
|---|---|---|---|
| `aishl_lesson_opens` | `analytics_useractivity` lesson_open → unit → course | course | `biz_aishl_lesson_opens` |
| `aishl_active_learners` | distinct users, lesson_open (+resource_view for `all`) | course, grain(day/week) | `biz_aishl_active_learners` |
| `aishl_signups` | `analytics_useractivity` signup ⋈ `analytics_userattribution` | utm_source | `biz_aishl_signups` |
| `aishl_paid_conversions` | `payments_conversionattribution` | tier, billing_period, utm_source | `biz_aishl_paid_conversions` |
| `aishl_new_mrr_eur` | `SUM(payments_conversionattribution.mrr_eur)` | tier, billing_period, utm_source | `biz_aishl_new_mrr_eur` |

- Lessons are SESSIONS, not pageviews: the app dedupes per user × unit
  within 30 min (`record_lesson_open`, `dedupe_minutes=30`). Unresolvable
  units (deleted course rows, non-numeric ids) land in `course='unknown'`.
- `grain` on `aishl_active_learners` is a deliberate addition to the
  catalog: weekly WAU rows (day = ISO Monday) would otherwise collide with
  the daily Monday row under the PK. The week row is rewritten daily as the
  week fills; D-1..D-7 settles the final value. WAU is overall only.
- `tier` NULL (one-off course purchase) → `'course'`; blank
  `billing_period` → `'one-off'`; blank `utm_source` → `'none'`;
  one-off `mrr_eur` NULL sums to 0. Pre-shipping subscriptions have no
  `ConversionAttribution` rows (no backfill) — those days read 0, not gaps.
- UTM sources use a fixed public-source allowlist: `telegram`, `newsletter`,
  `linkedin`, `youtube`, `google`, `github`, `twitter`, `slack`, `datatalks`,
  `email`. Values are trimmed and case folded; blank becomes `none`, and
  everything else becomes `other`. Arbitrary source values never enter
  `metric_daily` or VM labels. Billing periods are limited to `monthly`,
  `yearly`, `one-off`, and `other`. Course/tier slugs are operator-controlled.
- Every empty day has a zero row: lessons use `course=unknown`, learners
  use `course=all,grain=day`, signups use `utm_source=none`, and conversions
  and MRR use `tier=course,billing_period=one-off,utm_source=none`.
  These zero buckets indicate no events; they do not add counts.
- UTC week boundaries are explicit and remain stable across database
  timezone changes and daylight saving transitions. Numeric object IDs
  are matched as canonical text so malformed or oversized values are safe.
- Table names verified 2026-10-22 against the aisl checkout:
  `analytics_useractivity`, `analytics_userattribution` (PK `user_id`),
  `cb_curriculum_unit → cb_curriculum_module → cb_curriculum_course (slug)`
  (app label `cb_curriculum`), `payments_conversionattribution`,
  `payments_tier (slug)`.

Run with AISHL: add `BIZ_METRICS_AISHL_DSN=...` to the env from
`cron/biz-metrics.env.example`; the runner picks up `--metrics
aishl_lesson_opens aishl_active_learners aishl_signups
aishl_paid_conversions aishl_new_mrr_eur` (default = all registered metrics).

Hand-check one historic day (pg-shared, DB aisl):

```bash
psql "$BIZ_METRICS_AISHL_DSN" -c "SELECT c.slug, COUNT(*) FROM analytics_useractivity ua
  LEFT JOIN cb_curriculum_unit u ON ua.object_type='unit'
    AND u.id::text = ua.object_id
  LEFT JOIN cb_curriculum_module m ON m.id = u.module_id
  LEFT JOIN cb_curriculum_course c ON c.id = m.course_id
  WHERE ua.event_type='lesson_open'
    AND ua.occurred_at >= '2026-10-20+00' AND ua.occurred_at < '2026-10-21+00'
  GROUP BY 1;"
psql "$BIZ_METRICS_STORE_DSN" -c "SELECT dims, value FROM metric_daily
  WHERE day='2026-10-20' AND project='aishl' AND metric='aishl_lesson_opens';"
```

## Deploy (operator, contabo-b)

From an operator checkout, install the runner and then provision on the node:

```bash
# One-time prerequisite on contabo-b: sudo apt-get install python3-venv
./biz-metrics/install-biz-metrics.sh contabo-b
ssh contabo-b sudo python3 /data/biz-metrics/provision-biz-metrics.py
ssh contabo-b sudo /data/biz-metrics/run.sh
ssh contabo-b sudo bash /data/biz-metrics/check-dump.sh
```

The installer creates an isolated Python venv, root cron, and log rotation.
It preserves `/etc/biz-metrics.env` (root:root 0600), in the same private
configuration directory used by the existing dump job. Provisioning reads
container names from `/etc/coolify-pg-dump.env`, creates `biz_metrics` on
pg-shared, applies schema/grants, generates dedicated credentials on the
node, and adds `biz_metrics` to the existing dump list. Credentials never
pass through the operator box. Re-running preserves credentials; an
existing role without saved credentials requires private reconciliation.

Root cron is needed to read the root-only configuration and inspect Docker
network addresses. DB queries use only `biz_ro` column-level SELECT grants
and `biz_rw` SELECT/INSERT/UPDATE/DELETE on `metric_daily`. DELETE is scoped
to the current metric/day/platform within the same transaction as upserts,
so late status changes and resubmits remove stale dimension rows. Container
IPs are resolved on every run; no PostgreSQL port is published. Source
sessions use UTC, read-only defaults, and a two-minute statement timeout.

Debian/Ubuntu cron schedules in the **system timezone**. `TZ=` sets the job
environment; it does not change daemon scheduling. The installer requires
`Europe/Berlin` on the host and verifies the cron service is active. The
nightly entry is 01:30 local time. The data grain and D-1..D-7 window use UTC
calendar days (at 01:30 during summer time, the current UTC date still
belongs to the previous local day). Weekly AISHL rows use their ISO Monday,
which can precede the daily window.

With a remapped operator home, set `BIZ_METRICS_SSH_CONFIG` and
`BIZ_METRICS_SSH_IDENTITY` to the existing SSH configuration and key paths.
No credentials belong in command arguments, repository files, or reports.

VictoriaMetrics stores only two days locally in the current deployment;
PostgreSQL retains the durable recomputed history. VM reimports may retain
multiple raw samples with the same timestamp; no global deduplication or
retention settings are changed by this deployment. Use PostgreSQL for
canonical recomputed values and VMUI for the recent collect-only view.
To view yesterday, select yesterday's **UTC time range** in VMUI and query
`{__name__=~"biz_.*"}`. These historical samples need a historical range;
they are not current-time gauges. For an instant query, use yesterday at
00:01 UTC (the sample is at 00:00 UTC); the default short lookback will not
show it later in the day. `/api/v1/export` gives raw timestamp proof.

Disable scheduling by removing `/etc/cron.d/biz-metrics`; retain the DB and
private environment. Reinstalling restores the schedule. No alert changes
are part of this job.

## Textfile fallback

If `POST /api/v1/import/prometheus` is rejected from contabo-b, run with
`--no-push --textfile-dir <node_exporter textfile dir>`; the runner writes
`biz_metrics.prom` (gauges, no timestamps — textfile format has none).
Only the latest day per metric/label set is emitted, so a seven-day run does
not produce duplicate samples with the same label set. This fallback shows
latest observed daily aggregates at scrape time; use PostgreSQL for the
original historical day. Confirm the `:9100` collector runs with `--collector.textfile.directory` set
(already scraped per `configs/vm/prometheus.yml`); yesterday series then appear
via the normal `node` scrape job instead of the import endpoint.

## Tests

```bash
python3 -m pytest biz-metrics/tests/ -v          # pure tests; live fixtures skip without DSN
BIZMETRICS_TEST_DSN=... python3 -m pytest biz-metrics/tests/test_biz_metrics_cmp.py -v  # + live PG
python3 -m pytest biz-metrics/tests/test_biz_metrics_aishl.py -v  # AISHL: auto-starts own PG:16 container (needs docker)
```
