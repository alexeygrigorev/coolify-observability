-- relay_bounce_rate {client, stream} — P0 #3 (half).
-- Source: pg-relay / DB relay, table email_events.
-- Definition: bounce events on day D divided by sent events on day D, per
-- (client, stream). Stream: 'tx' when transactional_message_id IS NOT NULL,
-- 'campaign' when campaign_id IS NOT NULL. Rows with neither are excluded.
-- Day boundary: UTC calendar day; day taken from created_at.
-- Labels: client (clients.slug), stream. No PII, no campaign_id label.
-- Zero-guard: NULLIF(sent, 0) → NULL rate when there were no sends (runner
-- skips NULL rows for the VM push but still stores counts via the companion
-- base query; see runner.derive_rates).
-- Returns: (day DATE, dims JSONB, value NUMERIC rate 0..1).
-- Bind params: %(start)s (inclusive timestamptz), %(end)s (exclusive timestamptz).

WITH base AS (
    SELECT
        (e.created_at AT TIME ZONE 'UTC')::date AS day,
        c.slug AS client_slug,
        CASE
            WHEN e.transactional_message_id IS NOT NULL THEN 'tx'
            WHEN e.campaign_id IS NOT NULL THEN 'campaign'
        END AS stream,
        e.event_type AS event_type,
        COUNT(*)::numeric AS n
    FROM email_events e
    JOIN clients c ON c.id = e.client_id
    WHERE e.created_at >= %(start)s
      AND e.created_at < %(end)s
      AND e.event_type IN ('sent', 'bounce')
      AND (e.transactional_message_id IS NOT NULL OR e.campaign_id IS NOT NULL)
    GROUP BY 1, 2, 3, 4
),
pivot AS (
    SELECT
        day,
        client_slug,
        stream,
        SUM(CASE WHEN event_type = 'sent' THEN n ELSE 0 END) AS sent,
        SUM(CASE WHEN event_type = 'bounce' THEN n ELSE 0 END) AS bounced
    FROM base
    GROUP BY 1, 2, 3
)
SELECT
    day,
    jsonb_build_object('client', client_slug, 'stream', stream) AS dims,
    (bounced / NULLIF(sent, 0))::numeric AS value
FROM pivot
ORDER BY 1, 2;
