-- materialized: table
-- description: Product dimension with a margin band for reporting.
-- depends_on: stg_products

SELECT
    product_id,
    product_name,
    category,
    list_price,
    cost_price,
    unit_margin,
    CASE
        WHEN list_price IS NULL OR list_price = 0 THEN 'unknown'
        WHEN unit_margin / list_price >= 0.5 THEN 'high'
        WHEN unit_margin / list_price >= 0.3 THEN 'medium'
        ELSE 'low'
    END AS margin_band,
    CASE
        WHEN list_price < 20 THEN 'budget'
        WHEN list_price < 80 THEN 'mid'
        ELSE 'premium'
    END AS price_band,
    is_active
FROM stg_products
