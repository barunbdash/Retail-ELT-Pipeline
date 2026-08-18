-- materialized: view
-- description: Typed product catalogue with a derived margin.
-- depends_on: raw_products

SELECT
    TRIM(product_id)                                          AS product_id,
    TRIM(product_name)                                        AS product_name,
    LOWER(TRIM(category))                                     AS category,
    CAST(NULLIF(TRIM(list_price), '') AS DOUBLE)              AS list_price,
    CAST(NULLIF(TRIM(cost_price), '') AS DOUBLE)              AS cost_price,
    ROUND(
        CAST(NULLIF(TRIM(list_price), '') AS DOUBLE)
        - CAST(NULLIF(TRIM(cost_price), '') AS DOUBLE), 2
    )                                                         AS unit_margin,
    CASE WHEN LOWER(TRIM(is_active)) = 'true' THEN 1 ELSE 0 END AS is_active
FROM raw_products
WHERE NULLIF(TRIM(product_id), '') IS NOT NULL
