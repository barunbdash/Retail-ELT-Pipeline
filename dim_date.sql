-- materialized: table
-- description: Date spine covering every date observed in the order stream.
-- depends_on: stg_orders

-- Day of week is derived with Zeller's congruence rather than a vendor date
-- function, so the same SQL runs on DuckDB and SQLite. Zeller returns
-- 0 = Saturday, so it is shifted to 0 = Monday to match ISO weekday numbering.
WITH dates AS (
    SELECT DISTINCT order_date AS date_key FROM stg_orders
),
parts AS (
    SELECT
        date_key,
        CAST(SUBSTR(date_key, 1, 4) AS INTEGER)  AS year_number,
        CAST(SUBSTR(date_key, 6, 2) AS INTEGER)  AS month_number,
        CAST(SUBSTR(date_key, 9, 2) AS INTEGER)  AS day_number
    FROM dates
),
zeller AS (
    SELECT
        date_key,
        year_number,
        month_number,
        day_number,
        CASE WHEN month_number <= 2 THEN month_number + 12 ELSE month_number END AS z_month,
        CASE WHEN month_number <= 2 THEN year_number - 1 ELSE year_number END    AS z_year
    FROM parts
),
computed AS (
    SELECT
        date_key,
        year_number,
        month_number,
        day_number,
        -- FLOOR is explicit because DuckDB's `/` yields a double and CAST
        -- rounds rather than truncates. SQLite already floors integer division,
        -- so FLOOR is a no-op there and the two engines agree.
        (
            day_number
            + CAST(FLOOR((13 * (z_month + 1)) / 5.0) AS INTEGER)
            + (z_year % 100)
            + CAST(FLOOR((z_year % 100) / 4.0) AS INTEGER)
            + CAST(FLOOR(CAST(FLOOR(z_year / 100.0) AS INTEGER) / 4.0) AS INTEGER)
            + 5 * CAST(FLOOR(z_year / 100.0) AS INTEGER)
        ) % 7 AS zeller_dow
    FROM zeller
)
SELECT
    date_key,
    year_number,
    month_number,
    day_number,
    SUBSTR(date_key, 1, 7)                                  AS month_key,
    CAST(FLOOR((month_number + 2) / 3.0) AS INTEGER)         AS quarter_number,
    ((zeller_dow + 5) % 7) + 1                              AS iso_weekday,
    CASE ((zeller_dow + 5) % 7) + 1
        WHEN 1 THEN 'Monday'
        WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday'
        WHEN 5 THEN 'Friday'
        WHEN 6 THEN 'Saturday'
        ELSE 'Sunday'
    END                                                      AS weekday_name,
    CASE WHEN ((zeller_dow + 5) % 7) + 1 >= 6 THEN 1 ELSE 0 END AS is_weekend
FROM computed
