-- materialized: table
-- description: Line-grain fact with product and order context denormalised in.
-- depends_on: stg_order_lines, stg_orders, dim_product

SELECT
    l.order_id || '-' || CAST(l.line_number AS VARCHAR) AS order_line_key,
    l.order_id,
    l.line_number,
    l.product_id,
    o.customer_id,
    o.order_date,
    o.order_month,
    o.channel,
    o.status,
    p.category,
    p.margin_band,
    p.price_band,
    l.quantity,
    l.unit_price,
    l.discount_pct,
    l.gross_amount,
    l.discount_amount,
    l.net_amount,
    ROUND(l.quantity * COALESCE(p.cost_price, 0.0), 2)              AS cost_amount,
    ROUND(l.net_amount - l.quantity * COALESCE(p.cost_price, 0.0), 2) AS gross_profit,
    l.is_return
FROM stg_order_lines AS l
INNER JOIN stg_orders AS o ON o.order_id = l.order_id
LEFT JOIN dim_product AS p ON p.product_id = l.product_id
