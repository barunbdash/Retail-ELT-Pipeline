-- materialized: view
-- description: Typed and cleaned customer records from the CRM extract.
-- depends_on: raw_customers

SELECT
    TRIM(customer_id)                                        AS customer_id,
    NULLIF(TRIM(signup_date), '')                            AS signup_date,
    CAST(SUBSTR(TRIM(signup_date), 1, 4) AS INTEGER)         AS signup_year,
    SUBSTR(TRIM(signup_date), 1, 7)                          AS signup_month,
    UPPER(TRIM(country))                                     AS country,
    -- The CRM allows a blank segment. Downstream reporting needs a bucket,
    -- so unknowns are labelled rather than dropped.
    CASE
        WHEN NULLIF(TRIM(segment), '') IS NULL THEN 'unknown'
        ELSE LOWER(TRIM(segment))
    END                                                      AS segment,
    CASE
        WHEN LOWER(TRIM(marketing_opt_in)) IN ('true', '1', 'yes', 'y') THEN 1
        ELSE 0
    END                                                      AS is_marketing_opt_in,
    LOWER(TRIM(acquisition_channel))                         AS acquisition_channel
FROM raw_customers
WHERE NULLIF(TRIM(customer_id), '') IS NOT NULL
