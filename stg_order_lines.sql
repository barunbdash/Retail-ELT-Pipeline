-- materialized: table
-- description: Order lines with gross, discount and net amounts computed once.
-- depends_on: raw_order_lines

WITH typed AS (
    SELECT
        TRIM(order_id)                                    AS order_id,
        CAST(NULLIF(TRIM(line_number), '') AS INTEGER)    AS line_number,
        TRIM(product_id)                                  AS product_id,
        CAST(NULLIF(TRIM(quantity), '') AS INTEGER)       AS quantity,
        CAST(NULLIF(TRIM(unit_price), '') AS DOUBLE)      AS unit_price,
        COALESCE(CAST(NULLIF(TRIM(discount_pct), '') AS DOUBLE), 0.0) AS discount_pct,
        ROW_NUMBER() OVER (
            PARTITION BY TRIM(order_id), TRIM(line_number)
            ORDER BY TRIM(product_id)
        )                                                 AS duplicate_rank
    FROM raw_order_lines
    WHERE NULLIF(TRIM(order_id), '') IS NOT NULL
)
SELECT
    order_id,
    line_number,
    product_id,
    quantity,
    unit_price,
    discount_pct,
    ROUND(quantity * unit_price, 2)                                   AS gross_amount,
    ROUND(quantity * unit_price * discount_pct, 2)                    AS discount_amount,
    ROUND(quantity * unit_price * (1.0 - discount_pct), 2)            AS net_amount,
    -- Returns are booked as negative quantities on the original order rather
    -- than as separate credit notes. Flagging them keeps the sign convention
    -- explicit for anyone reading the fact table.
    CASE WHEN quantity < 0 THEN 1 ELSE 0 END                          AS is_return
FROM typed
WHERE duplicate_rank = 1
