-- relay_tx_messages {client, status, template_key} — P0 #1.
-- Source: pg-relay / DB relay, table transactional_messages.
-- Definition: count of transactional messages created on day D (UTC), by final
-- status. Day boundary: UTC calendar day. Recompute window D-1..D-7 settles
-- late SES status transitions (re-run is idempotent).
-- Labels: client (clients.slug), status, template_key. No PII.
-- Returns: (day DATE, dims JSONB, value NUMERIC).
-- Bind params: %(start)s (inclusive timestamptz), %(end)s (exclusive timestamptz).

SELECT
    (tm.created_at AT TIME ZONE 'UTC')::date AS day,
    jsonb_build_object(
        'client', c.slug,
        'status', tm.status,
        'template_key', tm.template_key
    ) AS dims,
    COUNT(*)::numeric AS value
FROM transactional_messages tm
JOIN clients c ON c.id = tm.client_id
WHERE tm.created_at >= %(start)s
  AND tm.created_at < %(end)s
GROUP BY 1, 2
ORDER BY 1, 2;
