# SQL metrics — contract for product intakes (B/C/D)

One file per metric: `sql/<project>/<metric>.sql` returning
`(day DATE, dims JSONB, value NUMERIC)` for bind window
`%(start)s` (incl) .. `%(end)s` (excl), UTC day boundary.

- `project` = directory name (`relay` reads `BIZ_RELAY_DSN`/pg-relay,
  `cmp`/`aisl`/`website` read `BIZ_SHARED_DSN`/pg-shared).
- `metric` = file stem, pushed as `biz_<metric>` with a `project` label.
- Copy `_template.sql` (skipped by the runner: `_`-prefixed files never run).
- Product intakes own their files: Relay → intake `d9d8bd81`,
  CMP → `6987cdae`, AISHL → `8cc61eb4`. Plumbing ships only the template.
- Re-runs of the D-1..D-7 window must return identical rows (idempotent).
- Dims: ≤ 8 keys, values ≤ 128 chars, never email/user_id/ip (dropped).
