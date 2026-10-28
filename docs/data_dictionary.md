# Data Dictionary

## Source

The dataset is **simulated**. No production data was available, so `src/00_make_dataset.py` generates an order log from an explicit generative model (seed `20250630`) and then injects ten realistic data-quality problems. The analysis scripts never read the generator's parameters. Because the patterns were planted, finding them shows that the *method* works, not that these effects exist in a real business.

| Property | Value |
|---|---|
| Customers simulated | 14,000 (13,979 placed at least one order before the snapshot) |
| Period | 2024-01-01 → 2025-06-30 (snapshot) |
| Raw rows | 42,776 (including injected duplicates, QA accounts and future-dated rows) |
| Clean rows | 41,783 orders, 13,959 customers |
| Assumed sampling | Treated as a 10% customer sample when grossing up to annual dollar figures (Phase 4 only) |

## Raw table: `data/raw/orders_data.csv`

| Column | Type | Description | Known issues (handled in Phase 1) |
|---|---|---|---|
| `order_id` | string | Order identifier | ~1.8% duplicated (double-submitted checkouts) |
| `user_id` | string | Customer identifier | 120 internal QA rows (`TEST_*`) |
| `order_date` | string | Order timestamp | Two formats (ISO and US M/D/Y); 128 future-dated rows |
| `order_amount` | float | Order value (USD) | Missing (~2.5%), negative (refund sign error), zero (comped), extreme outliers |
| `category` | string | Product category (Electronics, Home, Apparel, Beauty, Grocery, Sports) | Casing/whitespace variants; blanks |
| `discount_used` | mixed | Coupon used on this order | Mixed `1/0` and `Y/N` |
| `cs_tickets` | int | Customer-service contacts associated with the order | `-1` sentinel = unknown (legacy CRM) |
| `is_returned` | int | Order returned (0/1) | Schema extension added for this project |
| `channel` | string | Acquisition channel (Organic, Paid Search, Paid Social, Email/CRM, Affiliate) | Constant per customer |

## Processed tables (`data/processed/`)

### `orders_clean.csv`: one row per cleaned order

Raw columns (cleaned) plus:

| Column | Description |
|---|---|
| `cs_tickets_imputed`, `amount_sign_fixed`, `is_comped`, `amount_imputed`, `amount_winsorised` | Data-quality flags (0/1). Every repair is traceable. |
| `order_seq` | 0-based order number within the customer |
| `prev_date`, `next_date`, `days_since_prev`, `days_to_next` | Previous/next order of the same customer |
| `repeat_30d` | 1 if the customer's next order is within 30 days |
| `observable` | 1 if the order is ≥ 30 days before the snapshot (scoreable) |
| `cum_orders`, `cum_discount_rate`, `cum_return_rate`, `cum_tickets`, `cum_gmv`, `avg_gap_to_date` | Running customer history (expanding window up to and including this order) |
| `cohort_month`, `order_month`, `months_since_acq` | Cohort keys |
| `ticket_band` | `0`, `1`, `2`, `3+` |

**Timing note.** `cs_tickets` and `is_returned` describe the current order and are realised *after* purchase, possibly inside the 30-day outcome window. They are used as concurrent service exposures for attribution. With real data, filter them by timestamp before using them for prediction.

### `user_features.csv`: one row per customer

`cohort_month`, `channel`, `first_order`, `last_order`, `frequency`, `monetary`, `aov`, `total_tickets`, `max_tickets`, `return_rate`, `discount_rate`, `n_categories`, `primary_category`, `recency_days`, `tenure_days`, `avg_gap_days`, `is_repeater`, `R`, `F`, `M` (quintile scores), `rfm_score`, `rfm_segment`.

### `order_model_table.csv`

Scoreable orders only (`observable == 1`), with the modelling features listed in `src/01_clean_features.py`.

### `holdout_scored.csv`

Forward-in-time holdout (orders from 2025-02-01) with the gradient-boosting predicted probability `p_repeat`.

## Outputs

| Folder | Content |
|---|---|
| `outputs/tables/` | Every number in the report, as CSV. Prefix = phase (`01_` … `06_`). |
| `outputs/figures/` | Report charts (PNG) |
| `logs/` | Full text output of each phase, including row audits and test statistics |
