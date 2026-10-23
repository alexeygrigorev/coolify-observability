-- aishl_signups {utm_source} — P0 collect-only (t1127u-D).
-- analytics_useractivity signup rows (occurred_at = accounts_user
-- date_joined, written by the same post_save chokepoint that creates the
-- attribution row) LEFT JOIN analytics_userattribution (PK = user_id)
-- for first_touch_utm_source. Empty/blank sources fold to 'none';
-- case-folded so 'Telegram' and 'telegram' do not split a series.
-- UTM labels use a fixed ten-source allowlist; arbitrary input becomes 'other'.
-- Empty days emit one zero row at the default dimensions.
-- Params (psycopg): %(start)s, %(end)s as UTC day boundaries, [start, end).

WITH buckets AS (
    SELECT date_trunc('day', ua.occurred_at AT TIME ZONE 'UTC')::date AS day,
           jsonb_build_object(
               'utm_source',
               CASE
                   WHEN COALESCE(TRIM(att.first_touch_utm_source), '') = '' THEN 'none'
                   WHEN LOWER(TRIM(att.first_touch_utm_source)) IN (
                       'telegram', 'newsletter', 'linkedin', 'youtube', 'google',
                       'github', 'twitter', 'slack', 'datatalks', 'email'
                   ) THEN LOWER(TRIM(att.first_touch_utm_source))
                   ELSE 'other'
               END
           ) AS dims,
           COUNT(*)::numeric AS value
      FROM analytics_useractivity AS ua
      LEFT JOIN analytics_userattribution AS att
        ON att.user_id = ua.user_id
     WHERE ua.event_type = 'signup'
       AND ua.occurred_at >= %(start)s
       AND ua.occurred_at < %(end)s
     GROUP BY 1, 2
)
SELECT day, dims, value FROM buckets
UNION ALL
SELECT (%(start)s::timestamptz AT TIME ZONE 'UTC')::date,
       jsonb_build_object('utm_source', 'none'), 0::numeric
 WHERE NOT EXISTS (SELECT 1 FROM buckets)
 ORDER BY 1, 2;
