-- biz_metrics schema — Phase 1 collect-only store (t1127u).
-- Applied ONCE by the operator on the existing pg-shared instance:
--   createdb -h pg-shared -U postgres biz_metrics
--   psql -h pg-shared -U postgres -d biz_metrics -f schema.sql
--
-- App databases (cmp, website) are never migrated by this file.
-- Access: read-only role biz_ro (SELECT on listed tables only),
-- write role biz_rw (metric_daily only). Credentials live in the
-- existing secrets path on contabo-b, never in the repo.

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

-- Operator roles (review names against local secrets path before running):
--   CREATE ROLE biz_ro WITH LOGIN PASSWORD '<from secrets>';
--   GRANT CONNECT ON DATABASE cmp TO biz_ro;      -- repeat: website
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
--   CREATE ROLE biz_rw WITH LOGIN PASSWORD '<from secrets>';
--   GRANT ALL ON metric_daily TO biz_rw;
