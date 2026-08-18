-- materialized: table
-- description: Monthly clickstream funnel joined to realised order revenue.
-- depends_on: stg_web_events, fct_orders

WITH events AS (
    SELECT
        event_month,
        COUNT(DISTINCT session_id)                                                AS sessions,
        SUM(CASE WHEN event_type = 'page_view' THEN 1 ELSE 0 END)                 AS page_views,
        SUM(CASE WHEN event_type = 'add_to_cart' THEN 1 ELSE 0 END)               AS add_to_carts,
        SUM(CASE WHEN event_type = 'checkout_start' THEN 1 ELSE 0 END)            AS checkout_starts,
        SUM(CASE WHEN event_type = 'checkout_complete' THEN 1 ELSE 0 END)         AS checkout_completes
    FROM stg_web_events
    GROUP BY event_month
),
orders AS (
    SELECT
        order_month,
        COUNT(*)                        AS completed_orders,
        ROUND(SUM(net_amount), 2)       AS net_revenue
    FROM fct_orders
    WHERE is_completed = 1
    GROUP BY order_month
)
SELECT
    e.event_month,
    e.sessions,
    e.page_views,
    e.add_to_carts,
    e.checkout_starts,
    e.checkout_completes,
    ROUND(100.0 * e.add_to_carts / NULLIF(e.page_views, 0), 2)          AS cart_rate_pct,
    ROUND(100.0 * e.checkout_starts / NULLIF(e.add_to_carts, 0), 2)     AS checkout_rate_pct,
    ROUND(100.0 * e.checkout_completes / NULLIF(e.checkout_starts, 0), 2) AS completion_rate_pct,
    COALESCE(o.completed_orders, 0)                                     AS completed_orders,
    COALESCE(o.net_revenue, 0.0)                                        AS net_revenue
FROM events AS e
LEFT JOIN orders AS o ON o.order_month = e.event_month
