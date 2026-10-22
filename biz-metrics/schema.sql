-- biz_metrics durable store (system of record for business aggregates).
-- Database: biz_metrics on the EXISTING pg-shared instance (NOT inside app schemas).
-- Catalog: ~/tmp/agent-reports/business-metrics-catalog-t1127u-2026-10-22.md §1 + §4 Intake A.
-- Phase 1 = collect-only. No alert rules, no vmalert, no thresholds here.
--
-- Apply (operator, once, on pg-shared as superuser; secrets stay in the
-- existing contabo-b secrets path, never in this repo):
--   CREATE DATABASE biz_metrics OWNER biz_rw;
--   psql -d biz_metrics -f schema.sql
-- Roles and per-table grants live in roles.sql (applied per instance/DB).

CREATE TABLE IF NOT EXISTS metric_daily (
    day DATE NOT NULL,
    project TEXT NOT NULL,
    metric TEXT NOT NULL,
    dims JSONB NOT NULL DEFAULT '{}'::jsonb,
    value NUMERIC NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (day, project, metric, dims)
);

CREATE INDEX IF NOT EXISTS metric_daily_project_metric_day_idx
    ON metric_daily (project, metric, day DESC);

-- Operator roles (passwords out-of-band, see roles.sql; review names against
-- the local secrets path before running):
--   CREATE ROLE biz_ro WITH LOGIN PASSWORD '<from secrets>';
--   CREATE ROLE biz_rw WITH LOGIN PASSWORD '<from secrets>';
--   GRANT CONNECT ON DATABASE cmp TO biz_ro;      -- repeat: website
--   GRANT CONNECT ON DATABASE biz_metrics TO biz_rw;
--   GRANT USAGE ON SCHEMA public TO biz_ro;
--   GRANT SELECT (id, homework_id, submitted_at) ON courses_submission TO biz_ro;
--   GRANT SELECT (id, course_id, slug) ON courses_homework TO biz_ro;
--   GRANT SELECT (id, slug) ON courses_course TO biz_ro;
--   GRANT SELECT (id, campaign_id, course_id, status, created_at)
--     ON courses_courseregistration TO biz_ro;    -- CMP only; website has no status col
--   GRANT SELECT (id, slug) ON courses_registrationcampaign TO biz_ro;
--   -- pg-relay / DB relay (P0 Relay intake d9d8bd81):
--   GRANT CONNECT ON DATABASE relay TO biz_ro;
--   GRANT USAGE ON SCHEMA public TO biz_ro;
--   GRANT SELECT (id, client_id, status, template_key, created_at)
--     ON transactional_messages TO biz_ro;
--   GRANT SELECT (id, client_id, status, sent_at) ON campaigns TO biz_ro;
--   GRANT SELECT (id, campaign_id, status, sent_at, updated_at)
--     ON campaign_recipients TO biz_ro;
--   GRANT SELECT (id, client_id, campaign_id, transactional_message_id,
--     event_type, created_at) ON email_events TO biz_ro;
--   GRANT SELECT (id, slug) ON clients TO biz_ro;
--   GRANT SELECT, INSERT, UPDATE ON metric_daily TO biz_rw;
--   GRANT SELECT ON metric_daily TO biz_ro;
--   (full per-DB list in roles.sql; AISHL tables follow the same pattern)
