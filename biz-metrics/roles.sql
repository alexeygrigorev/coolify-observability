-- Least-privilege roles for biz-metrics (collect-only, Phase 1).
-- Secrets (passwords/DSNs) live ONLY in the existing contabo-b secrets path
-- (/etc/biz-metrics.env, mode 600) and are NEVER committed.
--
-- 1) On pg-shared (as superuser). Passwords are set out-of-band, e.g.:
--      CREATE ROLE biz_ro WITH LOGIN;
--      CREATE ROLE biz_rw WITH LOGIN;
--      ALTER ROLE biz_ro PASSWORD '<from existing secrets path>';
--      ALTER ROLE biz_rw PASSWORD '<from existing secrets path>';
--    (No passwords in this file or in git.)
--
-- 2) Per app DB on pg-shared (cmp, aisl, website) — run connected to EACH db:
--      GRANT CONNECT ON DATABASE cmp TO biz_ro;
--      GRANT USAGE ON SCHEMA public TO biz_ro;
--      -- then per metric table actually read (product intakes extend this list):
--      GRANT SELECT ON <table> TO biz_ro;
--    Product intakes (relay/cmp/aisl) document their exact table lists next to
--    their SQL files; the runner never needs more than SELECT on those tables.
--
-- 3) On pg-relay (as superuser, connected to DB relay):
--      GRANT CONNECT ON DATABASE relay TO biz_ro;
--      GRANT USAGE ON SCHEMA public TO biz_ro;
--      GRANT SELECT ON <relay metric tables> TO biz_ro;
--
-- 4) On the biz_metrics DB (connected to biz_metrics):
--      GRANT CONNECT ON DATABASE biz_metrics TO biz_rw;
--      GRANT USAGE ON SCHEMA public TO biz_ro, biz_rw;
--      GRANT SELECT, INSERT, UPDATE ON metric_daily TO biz_rw;
--      GRANT SELECT ON metric_daily TO biz_ro;
--    The runner writes ONLY via biz_rw on biz_metrics, and reads app DBs ONLY
--    via biz_ro. No DDL at runtime; schema changes are operator-applied.

-- Idempotent grants for the biz_metrics DB itself (safe to re-run):
GRANT USAGE ON SCHEMA public TO biz_ro, biz_rw;
GRANT SELECT, INSERT, UPDATE ON metric_daily TO biz_rw;
GRANT SELECT ON metric_daily TO biz_ro;
