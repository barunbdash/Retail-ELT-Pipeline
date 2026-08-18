-- materialized: view
-- description: Clickstream events, typed and bucketed by date.
-- depends_on: raw_web_events

SELECT
    TRIM(event_id)                                AS event_id,
    TRIM(customer_id)                             AS customer_id,
    LOWER(TRIM(event_type))                       AS event_type,
    TRIM(occurred_at)                             AS occurred_at,
    SUBSTR(TRIM(occurred_at), 1, 10)              AS event_date,
    SUBSTR(TRIM(occurred_at), 1, 7)               AS event_month,
    TRIM(session_id)                              AS session_id,
    LOWER(TRIM(device))                           AS device
FROM raw_web_events
WHERE NULLIF(TRIM(event_id), '') IS NOT NULL
