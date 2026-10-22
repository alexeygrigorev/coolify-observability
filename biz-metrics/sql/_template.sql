-- SQL metric contract (copy this file to sql/<project>/<metric>.sql and fill in).
-- Runner: biz-metrics/rollup.py. Phase 1 = collect-only (no thresholds here).
--
-- Rules:
--   1. Bind params %(start)s (inclusive timestamptz) and %(end)s (exclusive
--      timestamptz). The runner supplies the D-1..D-7 window (UTC) by default.
--   2. Return exactly (day DATE, dims JSONB, value NUMERIC), one row per
--      (day x dimension combo). day must be the UTC calendar day.
--   3. project = parent directory name (relay|cmp|aisl|website|...),
--      metric = file stem, pushed as biz_<metric> with a project="..." label.
--   4. dims keys become VM labels: keep <= 8, values <= 128 chars, and NEVER
--      email / user_id / ip (the runner drops those PII keys defensively).
--   5. Re-runs must give the same rows (idempotent upsert on
--      (day, project, metric, dims)).
-- Source routing: sql/relay/* reads BIZ_RELAY_DSN (pg-relay), everything else
-- reads BIZ_SHARED_DSN (pg-shared). Least-privilege biz_ro role (SELECT only).

SELECT
    (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date - 1 AS day,
    jsonb_build_object('example_dim', 'example') AS dims,
    0::numeric AS value
WHERE FALSE;  -- replace with the real aggregate GROUP BY 1, 2
