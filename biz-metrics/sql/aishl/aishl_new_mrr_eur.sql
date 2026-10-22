-- aishl_new_mrr_eur {tier, billing_period, utm_source} — P0 (t1127u-D).
-- SUM(payments_conversionattribution.mrr_eur): normalized monthly EUR
-- (amount for monthly, amount // 12 for yearly, NULL for one-off -> 0).
-- Same tier/billing_period/utm_source bucketing as aishl_paid_conversions
-- so revenue joins 1:1 with conversion counts.
-- Params (psycopg): %(start)s, %(end)s as UTC day boundaries, [start, end).

SELECT date_trunc('day', ca.created_at AT TIME ZONE 'UTC')::date AS day,
       jsonb_build_object(
           'tier', COALESCE(t.slug, 'course'),
           'billing_period', COALESCE(NULLIF(TRIM(ca.billing_period), ''), 'one-off'),
           'utm_source',
               COALESCE(NULLIF(LOWER(TRIM(ca.first_touch_utm_source)), ''), 'none')
       ) AS dims,
       COALESCE(SUM(ca.mrr_eur), 0)::numeric AS value
  FROM payments_conversionattribution AS ca
  LEFT JOIN payments_tier AS t
    ON t.id = ca.tier_id
 WHERE ca.created_at >= %(start)s
   AND ca.created_at < %(end)s
 GROUP BY 1, 2
 ORDER BY 1, 2;
