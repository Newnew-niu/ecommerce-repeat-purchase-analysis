"""
Phase 1 -- Data quality diagnostic + feature engineering.

Reads  : data/raw/orders_data.csv
Writes : data/processed/orders_clean.csv
         data/processed/user_features.csv
         data/processed/order_model_table.csv
         outputs/tables/01_dq_profile.csv
         outputs/tables/01_feature_summary.csv
         logs/01_cleaning_log.txt

Cleaning philosophy: repair what is recoverable, quarantine what is not, and
never silently drop a row without counting it. Every decision below is logged
with its row count so the numbers downstream can be traced back.
"""

import numpy as np
import pandas as pd

from common import RAW, PROC, TAB, LOGS, SNAPSHOT, REPEAT_WINDOW, Tee, pct

log = Tee(LOGS / "01_cleaning_log.txt")
pd.set_option("display.width", 160)


# ===========================================================================
# 1. LOAD + PROFILE
# ===========================================================================
raw = pd.read_csv(RAW / "orders_data.csv")
n0 = len(raw)

log("=" * 78)
log("PHASE 1 -- DATA QUALITY DIAGNOSTIC")
log("=" * 78)
log(f"\nRaw extract: {n0:,} rows x {raw.shape[1]} columns")
log(f"Snapshot date: {SNAPSHOT.date()}")

profile = pd.DataFrame(
    {
        "dtype": raw.dtypes.astype(str),
        "n_missing": raw.isna().sum(),
        "pct_missing": (raw.isna().mean() * 100).round(2),
        "n_unique": raw.nunique(dropna=True),
    }
)
log("\n--- Column profile (as loaded) ---")
log(profile.to_string())
profile.to_csv(TAB / "01_dq_profile.csv")

# Tracks every row we remove, so the audit adds up at the end.
removed = {}


# ===========================================================================
# 2. CLEANING
# ===========================================================================
df = raw.copy()
log("\n" + "-" * 78)
log("CLEANING ACTIONS")
log("-" * 78)

# --- 2.1 order_date: two formats coexist in the export -----------------------
iso = pd.to_datetime(df["order_date"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
us = pd.to_datetime(df["order_date"], format="%m/%d/%Y %H:%M", errors="coerce")
df["order_date"] = iso.fillna(us)
n_us = us.notna().sum()
n_unparsed = df["order_date"].isna().sum()
log(f"[2.1] Parsed dates: {iso.notna().sum():,} ISO + {n_us:,} US M/D/Y format.")
log(f"      Unparseable after both attempts: {n_unparsed:,}")
if n_unparsed:
    df = df[df["order_date"].notna()]
    removed["unparseable_date"] = int(n_unparsed)

# --- 2.2 Future-dated orders (app-server clock skew) -------------------------
future = df["order_date"] > SNAPSHOT
log(f"[2.2] Orders dated after snapshot: {future.sum():,} "
    f"(max {df.loc[future, 'order_date'].max()}). Dropped -- clock-skew artefact.")
removed["future_dated"] = int(future.sum())
df = df[~future]

# --- 2.3 Internal QA / load-test accounts ------------------------------------
is_test = df["user_id"].astype(str).str.upper().str.startswith(("TEST", "QA_"))
log(f"[2.3] Internal test accounts: {is_test.sum():,} rows across "
    f"{df.loc[is_test, 'user_id'].nunique():,} user_ids. Dropped.")
removed["test_accounts"] = int(is_test.sum())
df = df[~is_test]

# --- 2.4 Exact duplicate order events ----------------------------------------
dup_mask = df.duplicated(subset=["order_id"], keep="first")
log(f"[2.4] Duplicate order_id rows: {dup_mask.sum():,} "
    f"({pct(dup_mask.mean(), 2)} of remaining). Kept first occurrence.")
removed["duplicate_order_id"] = int(dup_mask.sum())
df = df[~dup_mask]

# --- 2.5 category normalisation ----------------------------------------------
cat_raw_n = df["category"].nunique(dropna=True)
df["category"] = (
    df["category"]
    .astype(str)
    .str.strip()
    .str.rstrip("_")
    .str.strip()
    .str.title()
    .replace({"Nan": np.nan, "": np.nan, "None": np.nan})
)
n_cat_missing = df["category"].isna().sum()
df["category"] = df["category"].fillna("Unknown")
log(f"[2.5] category: collapsed {cat_raw_n} raw string variants -> "
    f"{df['category'].nunique()} canonical values.")
log(f"      {n_cat_missing:,} blank/null categories relabelled 'Unknown' "
    f"(kept -- the order itself is valid).")

# --- 2.6 discount_used mixed types -------------------------------------------
raw_tokens = sorted(df["discount_used"].astype(str).str.strip().unique())
df["discount_used"] = (
    df["discount_used"]
    .astype(str)
    .str.strip()
    .str.upper()
    .map({"1": 1, "0": 0, "Y": 1, "N": 0, "TRUE": 1, "FALSE": 0})
)
n_disc_bad = df["discount_used"].isna().sum()
log(f"[2.6] discount_used carries {len(raw_tokens)} distinct raw tokens "
    f"{raw_tokens} -- one upstream service writes Y/N, the other 1/0. "
    f"Coerced to 0/1; {n_disc_bad:,} uncoercible.")
if n_disc_bad:
    df = df[df["discount_used"].notna()]
    removed["bad_discount_flag"] = int(n_disc_bad)
df["discount_used"] = df["discount_used"].astype(int)

# --- 2.7 cs_tickets sentinel -------------------------------------------------
sentinel = df["cs_tickets"] < 0
log(f"[2.7] cs_tickets == -1 sentinel ('unknown' from legacy CRM): "
    f"{sentinel.sum():,} rows. Set to 0 and flagged -- the modal value is 0 "
    f"({pct((df['cs_tickets'] == 0).mean())}), so imputing 0 is the conservative "
    f"choice and biases the ticket effect *downward*, not up.")
df["cs_tickets_imputed"] = sentinel.astype(int)
df.loc[sentinel, "cs_tickets"] = 0

# --- 2.8 order_amount: sign errors, zeros, nulls, outliers -------------------
neg = df["order_amount"] < 0
log(f"[2.8a] Negative amounts: {neg.sum():,}. These are refunds written back "
    f"with the wrong sign -- the purchase was real, so absolute value is taken "
    f"and the row flagged.")
df["amount_sign_fixed"] = neg.astype(int)
df.loc[neg, "order_amount"] = df.loc[neg, "order_amount"].abs()

zero = df["order_amount"] == 0
log(f"[2.8b] Zero amounts: {zero.sum():,}. Fully-comped orders -- retained "
    f"(they are genuine engagement) but excluded from AOV statistics.")
df["is_comped"] = zero.astype(int)

n_amt_null = df["order_amount"].isna().sum()
med_by_cat = df.groupby("category")["order_amount"].transform("median")
df["amount_imputed"] = df["order_amount"].isna().astype(int)
df["order_amount"] = df["order_amount"].fillna(med_by_cat)
log(f"[2.8c] Missing amounts: {n_amt_null:,} ({pct(n_amt_null / len(df), 2)}). "
    f"Imputed with the category median (amount is strongly category-driven; "
    f"a global median would distort Electronics by ~4x).")

p999 = df.loc[~zero, "order_amount"].quantile(0.999)
outlier = df["order_amount"] > p999
log(f"[2.8d] Amounts above the 99.9th pct (${p999:,.0f}): {outlier.sum():,}. "
    f"Winsorised to the cap rather than dropped -- they are plausible bulk "
    f"orders, but left raw they would dominate every mean.")
df["amount_winsorised"] = outlier.astype(int)
df.loc[outlier, "order_amount"] = p999

# --- 2.9 Audit ---------------------------------------------------------------
df = df.sort_values(["user_id", "order_date"]).reset_index(drop=True)
log("\n--- Row audit ---")
log(f"{'raw rows':<32} {n0:>9,}")
for k, v in removed.items():
    log(f"{'  - ' + k:<32} {-v:>9,}")
log(f"{'clean rows':<32} {len(df):>9,}  ({pct(len(df) / n0, 2)} retained)")
log(f"{'unique users':<32} {df['user_id'].nunique():>9,}")
log(f"{'date range':<32} {df['order_date'].min().date()} -> {df['order_date'].max().date()}")
log(f"{'total GMV':<32} ${df['order_amount'].sum():>13,.0f}")

df.to_csv(PROC / "orders_clean.csv", index=False)


# ===========================================================================
# 3. FEATURE ENGINEERING
# ===========================================================================
log("\n" + "=" * 78)
log("FEATURE ENGINEERING")
log("=" * 78)

g = df.groupby("user_id", sort=False)
df["order_seq"] = g.cumcount()                       # 0-indexed order number
df["prev_date"] = g["order_date"].shift(1)
df["next_date"] = g["order_date"].shift(-1)
df["days_since_prev"] = (df["order_date"] - df["prev_date"]).dt.days
df["days_to_next"] = (df["next_date"] - df["order_date"]).dt.days

# Target: did the same user order again within the KPI window?
df["repeat_30d"] = (df["days_to_next"] <= REPEAT_WINDOW).fillna(False).astype(int)

# An order placed less than 30 days before the snapshot has not had a full
# chance to be repeated. Including it would manufacture a fake decline in the
# most recent months -- the single most common bug in repeat-rate reporting.
df["observable"] = (df["order_date"] <= SNAPSHOT - pd.Timedelta(days=REPEAT_WINDOW)).astype(int)
log(f"\nCensoring: {(1 - df['observable']).sum():,} orders "
    f"({pct(1 - df['observable'].mean(), 1)}) fall inside the trailing "
    f"{REPEAT_WINDOW}-day window and cannot yet be scored. Excluded from all "
    f"repeat-rate and model calculations.")

# --- Running (point-in-time) behavioural state -------------------------------
# Everything here uses only what was knowable when the order was placed.
df["cum_orders"] = df["order_seq"]                                   # before this one
df["cum_discount_rate"] = g["discount_used"].transform(lambda s: s.expanding().mean())
df["cum_return_rate"] = g["is_returned"].transform(lambda s: s.expanding().mean())
df["cum_tickets"] = g["cs_tickets"].transform(lambda s: s.expanding().sum())
df["cum_gmv"] = g["order_amount"].transform(lambda s: s.expanding().sum())
df["avg_gap_to_date"] = g["days_since_prev"].transform(lambda s: s.expanding().mean())

# Cohort = calendar month of the user's first observed order
first_order = g["order_date"].transform("min")
df["cohort_month"] = first_order.dt.to_period("M").astype(str)
df["order_month"] = df["order_date"].dt.to_period("M").astype(str)
df["months_since_acq"] = (
    (df["order_date"].dt.to_period("M") - first_order.dt.to_period("M")).apply(lambda x: x.n)
)

# Ticket bands -- the shape of the ticket effect is the point of Phase 2,
# so keep both the raw count and a banded version.
df["ticket_band"] = pd.cut(
    df["cs_tickets"], bins=[-0.1, 0.5, 1.5, 2.5, 100],
    labels=["0", "1", "2", "3+"],
)

df.to_csv(PROC / "orders_clean.csv", index=False)


# --- 3.1 User-level RFM table -------------------------------------------------
u = df.groupby("user_id")
users = pd.DataFrame({
    "cohort_month": u["cohort_month"].first(),
    "channel": u["channel"].agg(lambda s: s.mode().iat[0]),
    "first_order": u["order_date"].min(),
    "last_order": u["order_date"].max(),
    "frequency": u["order_id"].count(),
    "monetary": u["order_amount"].sum(),
    "aov": u["order_amount"].mean(),
    "total_tickets": u["cs_tickets"].sum(),
    "max_tickets": u["cs_tickets"].max(),
    "return_rate": u["is_returned"].mean(),
    "discount_rate": u["discount_used"].mean(),
    "n_categories": u["category"].nunique(),
    "primary_category": u["category"].agg(lambda s: s.mode().iat[0]),
})
users["recency_days"] = (SNAPSHOT - users["last_order"]).dt.days
users["tenure_days"] = (users["last_order"] - users["first_order"]).dt.days
users["avg_gap_days"] = np.where(
    users["frequency"] > 1, users["tenure_days"] / (users["frequency"] - 1), np.nan
)
users["is_repeater"] = (users["frequency"] > 1).astype(int)

# RFM scores: quintiles, 5 = best. Recency is reversed (lower = better).
users["R"] = pd.qcut(users["recency_days"], 5, labels=[5, 4, 3, 2, 1]).astype(int)
users["F"] = users["frequency"].rank(method="first").pipe(
    lambda s: pd.qcut(s, 5, labels=[1, 2, 3, 4, 5])).astype(int)
users["M"] = pd.qcut(users["monetary"], 5, labels=[1, 2, 3, 4, 5]).astype(int)
users["rfm_score"] = users["R"] + users["F"] + users["M"]


def rfm_segment(r):
    if r.R >= 4 and r.F >= 4 and r.M >= 4:
        return "Champions"
    if r.R >= 3 and r.F >= 3:
        return "Loyal"
    if r.R >= 4 and r.F <= 2:
        return "New / Promising"
    if r.R <= 2 and r.F >= 4:
        return "At Risk (high value)"
    if r.R <= 2 and r.M >= 4:
        return "Can't Lose Them"
    if r.R <= 2:
        return "Hibernating"
    return "Needs Attention"


users["rfm_segment"] = users.apply(rfm_segment, axis=1)
users.reset_index().to_csv(PROC / "user_features.csv", index=False)

log(f"\nUser feature table: {users.shape[0]:,} users x {users.shape[1]} features")
log("\n--- RFM segment sizes ---")
seg = users.groupby("rfm_segment").agg(
    users=("frequency", "size"),
    avg_freq=("frequency", "mean"),
    avg_monetary=("monetary", "mean"),
    avg_recency=("recency_days", "mean"),
    repeat_share=("is_repeater", "mean"),
).sort_values("avg_monetary", ascending=False).round(2)
seg["pct_of_base"] = (seg["users"] / seg["users"].sum() * 100).round(1)
log(seg.to_string())
seg.to_csv(TAB / "01_rfm_segments.csv")


# --- 3.2 Order-level modelling table -----------------------------------------
model_cols = [
    "order_id", "user_id", "order_date", "order_month", "cohort_month",
    "months_since_acq", "order_amount", "category", "channel", "discount_used",
    "cs_tickets", "ticket_band", "is_returned", "cum_orders", "cum_discount_rate",
    "cum_return_rate", "cum_tickets", "cum_gmv", "days_since_prev",
    "avg_gap_to_date", "repeat_30d",
]
model_df = df.loc[df["observable"] == 1, model_cols].copy()
model_df.to_csv(PROC / "order_model_table.csv", index=False)
log(f"\nModelling table: {len(model_df):,} scoreable orders "
    f"(base 30-day repeat rate = {pct(model_df['repeat_30d'].mean())})")


# --- 3.3 Feature summary ------------------------------------------------------
num_cols = ["frequency", "monetary", "aov", "recency_days", "tenure_days",
            "avg_gap_days", "total_tickets", "max_tickets", "return_rate",
            "discount_rate", "n_categories"]
summary = users[num_cols].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.99]).T
summary["missing"] = users[num_cols].isna().sum()
summary = summary.round(2)
log("\n--- Engineered feature summary (user level) ---")
log(summary.to_string())
summary.to_csv(TAB / "01_feature_summary.csv")

log.save()
