-- materialized: table
-- description: Customer dimension with an unknown member for orphan foreign keys.
-- depends_on: stg_customers

-- The order extract runs an hour after the CRM extract, so a small share of
-- orders point at customers that are not in this dimension yet. Rather than
-- dropping revenue, those orders are routed to a surrogate 'UNKNOWN' member;
-- the data quality suite tracks how many, and alerts if the share grows.
SELECT
    customer_id,
    signup_date,
    signup_year,
    signup_month,
    country,
    segment,
    is_marketing_opt_in,
    acquisition_channel,
    0 AS is_unknown_member
FROM stg_customers

UNION ALL

SELECT
    'UNKNOWN'  AS customer_id,
    NULL       AS signup_date,
    NULL       AS signup_year,
    NULL       AS signup_month,
    'XX'       AS country,
    'unknown'  AS segment,
    0          AS is_marketing_opt_in,
    'unknown'  AS acquisition_channel,
    1          AS is_unknown_member
