-- aishl_paid_conversions {tier, billing_period, utm_source} — P0 (t1127u-D).
-- One row per paid Stripe checkout.session.completed
-- (payments_conversionattribution, created by
-- _record_conversion_attribution; never updated, so created_at is the
-- conversion day). tier NULL (one-off course purchase) -> 'course';
-- blank billing_period -> 'one-off'; blank utm_source -> 'none'.
-- Note: pre-shipping subscriptions have no rows (no backfill); those days
-- legitimately read 0, they are not gaps.
-- UTM labels use a fixed ten-source allowlist; arbitrary input becomes 'other'.
-- Empty days emit one zero row at the default dimensions.
-- Params (psycopg): %(start)s, %(end)s as UTC day boundaries, [start, end).

WITH buckets AS (
    SELECT date_trunc('day', ca.created_at AT TIME ZONE 'UTC')::date AS day,
           jsonb_build_object(
               'tier', COALESCE(t.slug, 'course'),
               'billing_period', CASE TRIM(ca.billing_period)
                   WHEN 'monthly' THEN 'monthly'
                   WHEN 'yearly' THEN 'yearly'
                   WHEN '' THEN 'one-off'
                   ELSE 'other'
               END,
               'utm_source',
                   CASE
                   WHEN COALESCE(TRIM(ca.first_touch_utm_source), '') = '' THEN 'none'
                   WHEN LOWER(TRIM(ca.first_touch_utm_source)) IN (
                       'telegram', 'newsletter', 'linkedin', 'youtube', 'google',
                       'github', 'twitter', 'slack', 'datatalks', 'email'
                   ) THEN LOWER(TRIM(ca.first_touch_utm_source))
                   ELSE 'other'
               END
           ) AS dims,
           COUNT(*)::numeric AS value
      FROM payments_conversionattribution AS ca
      LEFT JOIN payments_tier AS t
        ON t.id = ca.tier_id
     WHERE ca.created_at >= %(start)s
       AND ca.created_at < %(end)s
     GROUP BY 1, 2
)
SELECT day, dims, value FROM buckets
UNION ALL
SELECT (%(start)s::timestamptz AT TIME ZONE 'UTC')::date,
       jsonb_build_object('tier', 'course', 'billing_period', 'one-off', 'utm_source', 'none'), 0::numeric
 WHERE NOT EXISTS (SELECT 1 FROM buckets)
 ORDER BY 1, 2;
