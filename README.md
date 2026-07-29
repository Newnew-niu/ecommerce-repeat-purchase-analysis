# Repeat-Purchase Decline Analysis / 复购率下滑归因分析

End-to-end analysis of a B2C e-commerce order log: data cleaning → cohort analysis →
attribution modelling → business case.

**Main deliverable: [`REPORT.md`](REPORT.md)** (bilingual 中文/English).

---

## Data provenance / 数据来源

No production extract was available, so `src/00_make_dataset.py` simulates the order
log from an explicit generative model. Ground truth (ticket cliff, coupon dependency,
category repeat gradients, service degradation from 2024-10) is hard-coded in that
script only — **Phases 1–4 never read those parameters** and rediscover everything
from the CSV. Absolute dollar figures assume the extract is a 10% user sample; all
rates are unaffected.

没有拿到生产库权限，订单流水由生成脚本模拟。真实规律写死在 `00_make_dataset.py` 里，
下游脚本一律不读取，全部从 CSV 重新发现。金额基于「10% 抽样」假设外推，比率不受影响。

---

## Setup

```bash
pip install -r requirements.txt
```

Built and verified on Python 3.10.10. `requirements.txt` pins the exact versions
used; the pipeline is seeded and reproduces bit-identically on them.

## Run

`data/` is not tracked in this repo — it is ~19 MB of fully derived files that the
seeded generator rebuilds deterministically. **`00_make_dataset.py` is therefore a
required first step, not an optional one.**

```bash
cd src
python 00_make_dataset.py     # REQUIRED FIRST -- generates data/raw/orders_data.csv
python 01_clean_features.py   # Phase 1: cleaning + feature engineering
python 02_eda_cohort.py       # Phase 2: EDA, cohorts, tipping points
python 03_modeling.py         # Phase 3: logit + GBM attribution
python 04_roi.py              # Phase 4: business case
```

Scripts are order-dependent. Each writes a full log to `logs/` and results to
`outputs/`. Total runtime ~2 minutes.

To confirm your run matches the published report, check that
`outputs/tables/04_business_cases.csv` sums to a net contribution of **240,321**
and a net ROI of **0.7436** across the four base-case rows.

---

## Layout

```
src/                           analysis scripts + common.py
logs/                          per-phase audit logs (full numeric output)
outputs/figures/               10 charts
outputs/tables/                25 result tables
REPORT.md                      the deliverable

data/raw/orders_data.csv       generated locally -- 42,776 rows, intentionally dirty
data/processed/                generated locally -- cleaned orders, features, model table
```

`data/` is gitignored; both paths appear after you run `00_make_dataset.py`.

---

## Headline result

The reported 30-day repeat rate fell only 2.0pp and looked like noise. It was
masked by order-composition drift — 41.7% of 2025 orders come from deep-lifecycle
repeaters (vs 0% in 2024-01) who repeat at ~70%.

Measured survivorship-free, **new-user 30-day repeat fell 46.2% → 38.7%
(-7.5pp, -16.3% relative, p = 2.6e-11)** and cohort M+1 retention fell 34.7% → 27.2%.

Three drivers, all significant with user-clustered standard errors:

| Driver | Effect | Evidence |
|---|---|---|
| 3+ support contacts | OR 0.220 [0.161, 0.302] | cliff at the 3rd ticket, -18.4pp |
| Coupon dependency | OR 0.495 [0.452, 0.542] | -15.1pp, ≤40% vs ≥80% history |
| Electronics/Home category | OR 0.557 / 0.767 | tickets up 2.9x / 1.7x since 2024-01 |

Recommended portfolio: **$852k incremental GMV, $240k net contribution, 0.74x net ROI**
(3.2% of the $26.8M run-rate). 13 of 18 sensitivity scenarios are value-positive.

---

## Methodology notes worth reading

Three traps were hit and corrected during this analysis; each is documented in
`REPORT.md` rather than quietly fixed:

1. **Survivorship bias** — a "mature cohort calendar trend" test showed repeat
   *rising* 59% → 75%, because only hardcore repeaters from 2024 cohorts still
   order in 2025. Test discarded; M+1 retention used instead.
2. **Confounder placed as mediator** — the first mediation ladder introduced
   composition controls alongside the service variables, yielding an insignificant
   baseline that flipped sign and a meaningless "392% mediated". Confounders belong
   in the baseline.
3. **Mechanical confounding in dependency bands** — a one-and-done user who used a
   coupon has `cum_discount_rate = 1.0`. The raw top band was mostly one-order users,
   not dependent users. De-confounded by restricting to users with 3+ prior orders.

Also: 30-day censoring is applied (orders within 30 days of the snapshot are excluded,
or the most recent months show a fake decline); standard errors are clustered on
`user_id`; the train/test split is strictly forward-in-time; and every business case
faces a computed break-even gate rather than an asserted one.
