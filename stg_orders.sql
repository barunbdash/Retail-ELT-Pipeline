-- materialized: table
-- description: Deduplicated order headers with normalised currency and date parts.
-- depends_on: raw_orders

-- The order stream is at-least-once, so the same order_id can arrive more than
-- once. Keeping the first copy by ingestion order is enough here because
-- replays are byte-identical; a mutable source would need a version column.
WITH ranked AS (
    SELECT
        TRIM(order_id)                                    AS order_id,
        NULLIF(TRIM(customer_id), '')                     AS customer_id,
        TRIM(ordered_at)                                  AS ordered_at,
        LOWER(TRIM(status))                               AS status,
        LOWER(TRIM(channel))                              AS channel,
        LOWER(TRIM(payment_method))                       AS payment_method,
        UPPER(TRIM(currency))                             AS currency,
        COALESCE(CAST(NULLIF(TRIM(shipping_cost), '') AS DOUBLE), 0.0) AS shipping_cost,
        ROW_NUMBER() OVER (
            PARTITION BY TRIM(order_id)
            ORDER BY TRIM(ordered_at)
        )                                                 AS duplicate_rank
    FROM raw_orders
    WHERE NULLIF(TRIM(order_id), '') IS NOT NULL
)
SELECT
    order_id,
    customer_id,
    ordered_at,
    SUBSTR(ordered_at, 1, 10)                             AS order_date,
    SUBSTR(ordered_at, 1, 7)                              AS order_month,
    CAST(SUBSTR(ordered_at, 1, 4) AS INTEGER)             AS order_year,
    CAST(SUBSTR(ordered_at, 12, 2) AS INTEGER)            AS order_hour,
    status,
    channel,
    payment_method,
    currency,
    shipping_cost,
    CASE WHEN status = 'completed' THEN 1 ELSE 0 END      AS is_completed
FROM ranked
WHERE duplicate_rank = 1
