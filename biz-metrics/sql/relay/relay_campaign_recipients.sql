-- relay_campaign_recipients {client, status} — P0 #2.
-- Source: pg-relay / DB relay, campaign_recipients ⋈ campaigns.
-- Definition: campaign recipient rows that reached each status on day D (UTC).
-- "sent" is counted by sent_at day; every other terminal status
-- (skipped/failed/bounced/complained/unsubscribed) is counted by updated_at day,
-- because only sent_at is the send event while the rest settle via webhooks.
-- Day boundary: UTC calendar day. Pending rows are excluded (not reached).
-- Labels: client (campaigns.client_id → clients.slug), status. No PII.
-- Returns: (day DATE, dims JSONB, value NUMERIC).
-- Bind params: %(start)s (inclusive timestamptz), %(end)s (exclusive timestamptz).
-- Expected-empty: while campaign_recipients has zero rows this returns no
-- rows and pushes no series; it resumes automatically once qualifying
-- non-pending recipients fall inside the collected UTC day interval
-- (developer decision 2026-10-26, intake d9d8bd81).

SELECT
    s.day AS day,
    jsonb_build_object('client', s.client_slug, 'status', s.status) AS dims,
    COUNT(*)::numeric AS value
FROM (
    SELECT
        CASE
            WHEN cr.status = 'sent' THEN (cr.sent_at AT TIME ZONE 'UTC')::date
            ELSE (cr.updated_at AT TIME ZONE 'UTC')::date
        END AS day,
        c.slug AS client_slug,
        cr.status AS status
    FROM campaign_recipients cr
    JOIN campaigns camp ON camp.id = cr.campaign_id
    JOIN clients c ON c.id = camp.client_id
    WHERE cr.status <> 'pending'
      AND (
        (cr.status = 'sent' AND cr.sent_at >= %(start)s AND cr.sent_at < %(end)s)
        OR
        (cr.status <> 'sent' AND cr.updated_at >= %(start)s AND cr.updated_at < %(end)s)
      )
) s
WHERE s.day IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
