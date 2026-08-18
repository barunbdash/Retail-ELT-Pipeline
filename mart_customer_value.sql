-- materialized: table
-- description: Per-customer lifetime value, recency and an RFM-style segment.
-- depends_on: fct_orders, dim_customer

WITH customer_orders AS (
    SELECT
        customer_key,
        COUNT(*)                        AS order_count,
        SUM(net_amount)                 AS lifetime_net_revenue,
        MIN(order_date)                 AS first_order_date,
        MAX(order_date)                 AS last_order_date,
        SUM(has_return_line)            AS orders_with_returns
    FROM fct_orders
    WHERE is_completed = 1
    GROUP BY customer_key
),
observation AS (
    SELECT MAX(last_order_date) AS as_of_date FROM customer_orders
)
SELECT
    c.customer_id,
    c.country,
    c.segment,
    c.acquisition_channel,
    c.signup_month,
    COALESCE(o.order_count, 0)                              AS order_count,
    ROUND(COALESCE(o.lifetime_net_revenue, 0.0), 2)         AS lifetime_net_revenue,
    ROUND(
        COALESCE(o.lifetime_net_revenue, 0.0) / COALESCE(NULLIF(o.order_count, 0), 1), 2
    )                                                       AS average_order_value,
    o.first_order_date,
    o.last_order_date,
    COALESCE(o.orders_with_returns, 0)                      AS orders_with_returns,
    -- A coarse value tier is enough for most downstream slicing; anything
    -- finer belongs in a model, not in SQL.
    CASE
        WHEN COALESCE(o.lifetime_net_revenue, 0.0) >= 1500 THEN 'platinum'
        WHEN COALESCE(o.lifetime_net_revenue, 0.0) >= 600  THEN 'gold'
        WHEN COALESCE(o.lifetime_net_revenue, 0.0) >= 150  THEN 'silver'
        WHEN COALESCE(o.order_count, 0) > 0                THEN 'bronze'
        ELSE 'no_purchase'
    END                                                     AS value_tier,
    CASE
        WHEN o.last_order_date IS NULL THEN 'never_ordered'
        WHEN o.last_order_date >= SUBSTR(obs.as_of_date, 1, 7) || '-01' THEN 'active_this_month'
        ELSE 'lapsed'
    END                                                     AS recency_bucket
FROM dim_customer AS c
LEFT JOIN customer_orders AS o ON o.customer_key = c.customer_id
CROSS JOIN observation AS obs
WHERE c.is_unknown_member = 0
