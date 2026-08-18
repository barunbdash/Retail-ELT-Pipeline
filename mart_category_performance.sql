-- materialized: table
-- description: Monthly margin and return rate by product category.
-- depends_on: fct_order_lines

SELECT
    order_month,
    category,
    COUNT(DISTINCT order_id)                              AS order_count,
    SUM(quantity)                                         AS units_sold,
    ROUND(SUM(gross_amount), 2)                           AS gross_revenue,
    ROUND(SUM(net_amount), 2)                             AS net_revenue,
    ROUND(SUM(cost_amount), 2)                            AS cost_of_goods,
    ROUND(SUM(gross_profit), 2)                           AS gross_profit,
    ROUND(
        100.0 * SUM(gross_profit) / NULLIF(SUM(net_amount), 0), 2
    )                                                     AS gross_margin_pct,
    ROUND(
        100.0 * SUM(CASE WHEN is_return = 1 THEN 1 ELSE 0 END) / COUNT(*), 2
    )                                                     AS return_line_pct
FROM fct_order_lines
WHERE status = 'completed' AND category IS NOT NULL
GROUP BY order_month, category
