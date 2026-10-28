-- ============================================================================
-- KPI queries -- independent SQL re-implementation of the core metrics.
--
-- Dialect : SQLite >= 3.25 (window functions). Portable to PostgreSQL /
--           BigQuery / Snowflake by swapping julianday() for date arithmetic.
-- Table   : orders(order_id, user_id, order_date TEXT 'YYYY-MM-DD HH:MM:SS',
--                  order_amount REAL, category TEXT)
--           loaded from data/processed/orders_clean.csv by src/06_sql_checks.py.
-- Params  : :censor_cutoff -- snapshot minus 30 days ('2025-05-31 00:00:00').
--           An order placed after this has not had 30 days to be repeated.
--
-- These queries deliberately use ONLY raw columns. The "next order" is derived
-- here with LEAD(), not read from the pandas-engineered days_to_next column,
-- so agreement with the Python outputs is a genuine cross-check.
--
-- Each query starts with a "-- name:" marker that 06_sql_checks.py uses to
-- find it.
-- ============================================================================


-- name: order_sequence
-- Helper view: every order with the customer's order number and next order date.
CREATE TEMP VIEW order_seq AS
SELECT
    order_id,
    user_id,
    order_date,
    order_amount,
    category,
    ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY order_date) - 1 AS order_seq,
    LEAD(order_date) OVER (PARTITION BY user_id ORDER BY order_date)  AS next_date,
    MIN(order_date) OVER (PARTITION BY user_id)                        AS first_date
FROM orders;


-- name: overall_kpis
-- Orders, active customers, GMV, AOV (GMV / orders), purchase frequency.
SELECT
    COUNT(*)                                   AS orders,
    COUNT(DISTINCT user_id)                    AS customers,
    SUM(order_amount)                          AS gmv,
    SUM(order_amount) / COUNT(*)               AS aov,
    1.0 * COUNT(*) / COUNT(DISTINCT user_id)   AS purchase_frequency
FROM orders;


-- name: headline_repeat_by_month
-- Order-level 30-day repeat rate (the "headline" KPI), by order month.
-- Denominator: orders on or before the censoring cutoff.
-- Numerator  : those followed by the same customer's next order within 30 days.
SELECT
    substr(order_date, 1, 7)                                            AS order_month,
    COUNT(*)                                                            AS orders,
    AVG(CASE WHEN next_date IS NOT NULL
              AND CAST(julianday(next_date) - julianday(order_date) AS INTEGER) <= 30
             THEN 1.0 ELSE 0.0 END)                                     AS headline_repeat
FROM order_seq
WHERE julianday(order_date) <= julianday(:censor_cutoff)
GROUP BY order_month
ORDER BY order_month;


-- name: new_customer_repeat_by_cohort
-- New-customer 30-day repeat rate, by acquisition month.
-- Unit: customer. Denominator: customers whose FIRST order is on or before the
-- cutoff. Numerator: those whose second order came within 30 days of the first.
SELECT
    substr(order_date, 1, 7)                                            AS cohort_month,
    COUNT(*)                                                            AS new_users,
    AVG(CASE WHEN next_date IS NOT NULL
              AND CAST(julianday(next_date) - julianday(order_date) AS INTEGER) <= 30
             THEN 1.0 ELSE 0.0 END)                                     AS new_user_repeat
FROM order_seq
WHERE order_seq = 0
  AND julianday(order_date) <= julianday(:censor_cutoff)
GROUP BY cohort_month
ORDER BY cohort_month;


-- name: cohort_m1_retention
-- Cohort M+1 retention: share of a cohort with >= 1 order in the calendar month
-- after the acquisition month. The last cohort (no M+1 yet) is excluded.
WITH user_months AS (
    SELECT DISTINCT
        user_id,
        substr(first_date, 1, 7)                                        AS cohort,
        (CAST(substr(order_date, 1, 4) AS INTEGER) * 12 + CAST(substr(order_date, 6, 2) AS INTEGER))
      - (CAST(substr(first_date, 1, 4) AS INTEGER) * 12 + CAST(substr(first_date, 6, 2) AS INTEGER))
                                                                        AS m_idx
    FROM order_seq
)
SELECT
    cohort,
    COUNT(DISTINCT user_id)                                             AS cohort_size,
    1.0 * COUNT(DISTINCT CASE WHEN m_idx = 1 THEN user_id END)
        / COUNT(DISTINCT user_id)                                       AS m1_retention
FROM user_months
GROUP BY cohort
HAVING cohort < '2025-06'
ORDER BY cohort;


-- name: aov_by_category
-- AOV and order share by category.
SELECT
    category,
    COUNT(*)                                            AS orders,
    SUM(order_amount) / COUNT(*)                        AS aov,
    1.0 * COUNT(*) / (SELECT COUNT(*) FROM orders)      AS order_share
FROM orders
GROUP BY category
ORDER BY aov DESC;


-- name: time_to_second_order
-- Median days from first to second order, among customers with a second order.
-- (SQLite has no MEDIAN(); this uses the row-number midpoint.)
WITH gaps AS (
    SELECT CAST(julianday(next_date) - julianday(order_date) AS INTEGER) AS days
    FROM order_seq
    WHERE order_seq = 0 AND next_date IS NOT NULL
),
ranked AS (
    SELECT days,
           ROW_NUMBER() OVER (ORDER BY days) AS rn,
           COUNT(*) OVER ()                  AS n
    FROM gaps
)
SELECT AVG(days) AS median_days
FROM ranked
WHERE rn IN ((n + 1) / 2, (n + 2) / 2);
