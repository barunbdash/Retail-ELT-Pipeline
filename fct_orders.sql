-- materialized: table
-- description: One row per order, with line totals rolled up and FKs resolved.
-- depends_on: stg_orders, stg_order_lines, dim_customer

WITH line_rollup AS (
    SELECT
        order_id,
        COUNT(*)                       AS line_count,
        SUM(quantity)                  AS total_quantity,
        SUM(gross_amount)              AS gross_amount,
        SUM(discount_amount)           AS discount_amount,
        SUM(net_amount)                AS net_amount,
        MAX(is_return)                 AS has_return_line
    FROM stg_order_lines
    GROUP BY order_id
)
SELECT
    o.order_id,
    -- Orphan foreign keys are conformed to the unknown member instead of being
    -- silently lost to an inner join.
    CASE WHEN c.customer_id IS NULL THEN 'UNKNOWN' ELSE o.customer_id END AS customer_key,
    o.customer_id                                    AS source_customer_id,
    o.order_date,
    o.order_month,
    o.order_year,
    o.order_hour,
    o.status,
    o.channel,
    o.payment_method,
    o.currency,
    o.is_completed,
    COALESCE(l.line_count, 0)                        AS line_count,
    COALESCE(l.total_quantity, 0)                    AS total_quantity,
    ROUND(COALESCE(l.gross_amount, 0.0), 2)          AS gross_amount,
    ROUND(COALESCE(l.discount_amount, 0.0), 2)       AS discount_amount,
    ROUND(COALESCE(l.net_amount, 0.0), 2)            AS net_amount,
    o.shipping_cost,
    ROUND(COALESCE(l.net_amount, 0.0) + o.shipping_cost, 2) AS total_amount,
    COALESCE(l.has_return_line, 0)                   AS has_return_line,
    CASE WHEN c.customer_id IS NULL THEN 1 ELSE 0 END AS is_orphan_customer
FROM stg_orders AS o
LEFT JOIN line_rollup AS l ON l.order_id = o.order_id
LEFT JOIN dim_customer AS c ON c.customer_id = o.customer_id AND c.is_unknown_member = 0
