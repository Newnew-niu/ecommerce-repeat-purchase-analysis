# KPI Definitions

Every KPI below is implemented once in [`src/kpis.py`](../src/kpis.py). That module is used by the analysis (`src/05_kpis_robustness.py`), the dashboard (`dashboard/app.py`) and the tests. The core metrics are also re-implemented independently in SQL ([`sql/kpi_queries.sql`](../sql/kpi_queries.sql)) and cross-checked by `src/06_sql_checks.py`.

**Global conventions**

| Convention | Value |
|---|---|
| Snapshot date | 2025-06-30. Nothing after it is used. |
| Repeat window | 30 days (`REPEAT_WINDOW` in `src/common.py`); 60 and 90 days tested as robustness checks |
| Censoring | An order (or a first order) placed less than *window* days before the snapshot is **excluded** from repeat rates, because its outcome is not yet observable. Without this, the latest months always show a fake decline. |
| Customer | `user_id`, after removing internal QA accounts |
| Order | `order_id` after de-duplication and removal of future-dated rows; zero-value (comped) orders count as orders |
| Revenue | `order_amount` after cleaning (sign fixed, missing values imputed with category median, winsorised at p99.9). Called GMV. Refunds/returns are flagged (`is_returned`) but **not** netted out of GMV. |
| Acquisition cohort | Calendar month of the customer's first observed order |

---

## Repeat and retention metrics

These are **not interchangeable**. They use different counting units and denominators and answer different questions. Confusing them is exactly how the decline in this project went unnoticed.

| KPI | Question it answers | Unit | Numerator | Denominator | Window |
|---|---|---|---|---|---|
| **Order-level 30-day repeat rate** ("headline") | How often is an order followed by another order? | Order | Scoreable orders followed by the same customer's next order within 30 days | Orders placed ≥ 30 days before the snapshot | 30 days after each order |
| **New-customer 30-day repeat rate** | Do newly acquired customers come back? | Customer | First-time customers whose 2nd order is within 30 days of their 1st | First-time customers whose 1st order is ≥ 30 days before the snapshot | 30 days after first order |
| **90-day repeat customer rate** | Same, with a longer window | Customer | New customers with a 2nd order within 90 days | New customers acquired ≥ 90 days before the snapshot | 90 days after first order |
| **Cohort M+n retention** | What share of a cohort is active n months later? | Customer × calendar month | Cohort customers with ≥ 1 order in calendar month M+n | Cohort size | Calendar month n after acquisition month |
| **Established-customer repeat** | Is behaviour changing for loyal customers? | Order | Orders by customers with ≥ 3 prior orders that are followed by another order within 30 days | Scoreable orders by customers with ≥ 3 prior orders | 30 days |

**Why the headline rate misleads.** It is weighted by order volume, so heavy repeat customers count many times. As the base matures, their share of orders grows (0% → 42% of orders here), and the average stays flat even while every customer group gets worse. Use it for operations, not for judging retention.

**Why not "% of customers with 2+ orders ever".** That measure depends on tenure: customers acquired last month have had no time to reorder, so it falls mechanically for recent cohorts. A fixed window (30- or 90-day repeat customer rate) removes this bias. The "ever" version is used in this project only to split GMV between one-time and repeat customers, never for trends.

**Retention rate vs cohort retention.** A period retention rate (customers active this period who were also active last period) mixes cohorts. Cohort retention keeps the acquisition month fixed, which is what lets this analysis show that *every cohort since 2024-11* retains worse.

**Calendar-month caveat.** M+1 uses calendar months, so a customer acquired on Jan 31 who reorders on Feb 1 counts as retained at M+1. This is the standard convention; it adds noise but no bias between cohorts.

---

## Value and frequency metrics

| KPI | Definition | Unit | Notes |
|---|---|---|---|
| **GMV** | Sum of cleaned `order_amount` | — | Gross of returns and coupons |
| **Average order value (AOV)** | GMV ÷ number of orders | Order | Includes comped (zero-value) orders, which lower it by ~0.3% |
| **Purchase frequency** | Orders ÷ active customers in the selected period | Customer | Not lifetime-normalised; compare only periods of equal length |
| **Time to second order** | Days from 1st to 2nd order | Customer | **Conditional** on having a 2nd order. Do not read it as "how long everyone takes". For trend comparisons, restrict to customers with equal observation time (Phase 5 uses ≥ 180 days). |
| **Customer lifetime GMV** | Sum of a customer's GMV to the snapshot | Customer | Observed, not predicted; biased low for recent customers |
| **Revenue by segment** | GMV grouped by RFM segment or customer type | — | RFM quintiles are scored at the snapshot date |

## Metrics deliberately not reported

| Metric | Why not |
|---|---|
| Net revenue / profit per order | No cost, refund-value or coupon-value fields in the data. Phase 4 uses an *assumed* 42% contribution margin for planning only. |
| Predicted CLV | Would need a validated survival or BG/NBD model; out of scope. Phase 4 uses an observed continuation chain instead. |
| Churn rate | No contractual end event; "churn" would be an arbitrary inactivity threshold. Cohort retention conveys the same information without the threshold. |
