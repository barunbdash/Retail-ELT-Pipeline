-- materialized: table
-- description: Daily completed revenue by channel, with weekday context.
-- depends_on: fct_orders, dim_date

SELECT
    f.order_date,
    d.month_key,
    d.weekday_name,
    d.is_weekend,
    f.channel,
    COUNT(*)                                          AS order_count,
    COUNT(DISTINCT f.customer_key)                    AS customer_count,
    ROUND(SUM(f.gross_amount), 2)                     AS gross_revenue,
    ROUND(SUM(f.discount_amount), 2)                  AS discount_total,
    ROUND(SUM(f.net_amount), 2)                       AS net_revenue,
    ROUND(SUM(f.shipping_cost), 2)                    AS shipping_revenue,
    ROUND(SUM(f.net_amount) / COUNT(*), 2)            AS average_order_value
FROM fct_orders AS f
INNER JOIN dim_date AS d ON d.date_key = f.order_date
WHERE f.is_completed = 1
GROUP BY f.order_date, d.month_key, d.weekday_name, d.is_weekend, f.channel
