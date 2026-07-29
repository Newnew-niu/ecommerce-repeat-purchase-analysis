"""
Phase 2 -- EDA, cohort retention, segment profiling, tipping-point detection.

Reads  : data/processed/{orders_clean,user_features,order_model_table}.csv
Writes : outputs/figures/02_*.png, outputs/tables/02_*.csv, logs/02_eda_log.txt

Driving question: the repeat KPI is soft, but is it a MIX effect (we bought worse
users) or a SERVICE effect (we got worse at keeping the users we had)? Those have
opposite fixes, so most of this phase is about measuring repeat in a way that
cannot be faked by composition drift.

Three metric definitions are used deliberately:
  * headline_repeat    -- all scoreable orders. This is what the business reports.
                          It is composition-weighted and therefore misleading.
  * new_user_repeat    -- share of a month's NEW users who order again <=30d.
                          No survivorship, no composition. The honest acquisition metric.
  * established_repeat -- orders placed by users with >=3 prior orders. Fixed
                          lifecycle position, so calendar movement is real.
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

from common import PROC, FIG, TAB, LOGS, SNAPSHOT, CATEGORY_ORDER, Tee, pct

log = Tee(LOGS / "02_eda_log.txt")
sns.set_theme(style="whitegrid", context="talk")
plt.rcParams["figure.dpi"] = 120
plt.rcParams["savefig.bbox"] = "tight"
plt.rcParams["axes.titleweight"] = "bold"

MIN_CELL = 30   # never report a rate off fewer than this many orders

orders = pd.read_csv(PROC / "orders_clean.csv", parse_dates=["order_date"])
users = pd.read_csv(PROC / "user_features.csv", parse_dates=["first_order", "last_order"])
model = pd.read_csv(PROC / "order_model_table.csv", parse_dates=["order_date"])

log("=" * 78)
log("PHASE 2 -- EDA / COHORT / TIPPING POINT")
log("=" * 78)

# High-value USER (not high-value order): top tercile of personal AOV.
hv_cut = users["aov"].quantile(2 / 3)
hv_users = set(users.loc[users["aov"] >= hv_cut, "user_id"])
model["hv_user"] = model["user_id"].isin(hv_users).astype(int)
orders["hv_user"] = orders["user_id"].isin(hv_users).astype(int)
log(f"\nHigh-value user definition: personal AOV >= ${hv_cut:,.2f} (top tercile) "
    f"-> {len(hv_users):,} users ({pct(len(hv_users) / len(users))} of base), "
    f"{pct(model.hv_user.mean())} of scoreable orders.")


# ===========================================================================
# 1. THREE VIEWS OF THE SAME KPI
# ===========================================================================
log("\n" + "-" * 78)
log("1. TREND -- headline vs new-user vs established-user repeat")
log("-" * 78)

# --- 1a. Headline (composition-weighted) -------------------------------------
headline = model.groupby("order_month")["repeat_30d"].agg(["size", "mean"])

# --- 1b. New-user repeat: did a first-time buyer come back within 30 days? ----
firsts = model[model.cum_orders == 0].copy()
new_user = firsts.groupby("cohort_month")["repeat_30d"].agg(["size", "mean"])

# --- 1c. Established users at a fixed lifecycle position ---------------------
est = model[model.cum_orders >= 3]
established = est.groupby("order_month")["repeat_30d"].agg(["size", "mean"])

view = pd.DataFrame({
    "orders": headline["size"],
    "headline_repeat": headline["mean"].round(4),
    "new_users": new_user["size"],
    "new_user_repeat": new_user["mean"].round(4),
    "est_orders": established["size"],
    "established_repeat": established["mean"].round(4),
    "avg_tickets": model.groupby("order_month")["cs_tickets"].mean().round(4),
    "discount_share": model.groupby("order_month")["discount_used"].mean().round(4),
    "return_rate": model.groupby("order_month")["is_returned"].mean().round(4),
})
log("\n" + view.to_string())
view.to_csv(TAB / "02_monthly_trend.csv")

log("\n>>> The headline metric is nearly flat while new-user repeat falls off a "
    "cliff. That gap IS the finding: the reported KPI is being propped up by a "
    "shrinking core of heavy repeaters placing more of the total orders.")

# Order-mix proof of the above
mix = model.groupby("order_month").apply(
    lambda d: pd.Series({
        "share_orders_from_4plus": (d.cum_orders >= 4).mean(),
        "share_orders_from_new": (d.cum_orders == 0).mean(),
    }), include_groups=False).round(4)
log("\n--- Order composition drift (why the headline is flattered) ---")
log(mix.to_string())
mix.to_csv(TAB / "02_order_mix_drift.csv")


def compare(frame, label, base_q, recent_q, value="repeat_30d"):
    """Two-period proportion comparison with a chi-square test."""
    sub = frame[frame.quarter.isin(base_q + recent_q)].copy()
    sub["period"] = np.where(sub.quarter.isin(recent_q), "recent", "base")
    ct = pd.crosstab(sub["period"], sub[value])
    chi2, p, _, _ = stats.chi2_contingency(ct)
    a = sub.loc[sub.period == "base", value]
    b = sub.loc[sub.period == "recent", value]
    d = b.mean() - a.mean()
    log(f"\n{label}")
    log(f"  {'/'.join(base_q)}: {pct(a.mean())} (n={len(a):,})")
    log(f"  {'/'.join(recent_q)}: {pct(b.mean())} (n={len(b):,})")
    log(f"  delta = {d * 100:+.1f} pp | relative = {d / a.mean() * 100:+.1f}% "
        f"| chi2 = {chi2:.1f} | p = {p:.3e}")
    return d, p


model["quarter"] = model["order_date"].dt.to_period("Q").astype(str)
firsts["quarter"] = firsts["order_date"].dt.to_period("Q").astype(str)
BASE_Q, RECENT_Q = ["2024Q2", "2024Q3"], ["2025Q1", "2025Q2"]

log("\n" + "-" * 78)
log("QUARTER-OVER-QUARTER TESTS (2024Q2-Q3 baseline vs 2025Q1-Q2)")
log("-" * 78)
d_head, _ = compare(model, "[Headline] all scoreable orders", BASE_Q, RECENT_Q)
d_new, p_new = compare(firsts, "[New users] first-order 30-day repeat", BASE_Q, RECENT_Q)
d_new_hv, p_new_hv = compare(firsts[firsts.hv_user == 1],
                             "[New HIGH-VALUE users] first-order 30-day repeat",
                             BASE_Q, RECENT_Q)
d_est, p_est = compare(model[model.cum_orders >= 3],
                       "[Established users, >=3 prior orders]", BASE_Q, RECENT_Q)


# ===========================================================================
# 2. COHORT MATRIX
# ===========================================================================
log("\n" + "-" * 78)
log("2. COHORT RETENTION")
log("-" * 78)

first_period = orders.groupby("user_id")["order_date"].min().dt.to_period("M")
orders["cohort"] = orders["user_id"].map(first_period).astype(str)
orders["m_idx"] = (orders["order_date"].dt.to_period("M")
                   - orders["user_id"].map(first_period)).apply(lambda x: x.n)

cohort_sizes = orders.groupby("cohort")["user_id"].nunique()
active = orders.groupby(["cohort", "m_idx"])["user_id"].nunique().unstack(fill_value=0)
retention = active.div(cohort_sizes, axis=0)
for c in retention.index:                       # mask the un-happened future
    horizon = (SNAPSHOT.to_period("M") - pd.Period(c, "M")).n
    retention.loc[c, [m for m in retention.columns if m > horizon]] = np.nan

log(f"\nCohort retention matrix -- {len(retention)} cohorts, "
    f"{cohort_sizes.sum():,} users. Cell = % of cohort placing an order in M+n.")
log("\n" + (retention * 100).round(1).iloc[:, :10].to_string())
retention.to_csv(TAB / "02_cohort_retention.csv")

m1 = (retention[1] * 100).dropna()
log("\n--- M+1 retention by cohort (survivorship-free acquisition quality) ---")
log(m1.round(1).to_string())
early_m1 = m1.loc["2024-01":"2024-09"].mean()
late_m1 = m1.loc["2024-11":"2025-05"].mean()
log(f"\n  2024-01..2024-09 average M+1 = {early_m1:.1f}%")
log(f"  2024-11..2025-05 average M+1 = {late_m1:.1f}%")
log(f"  decay = {late_m1 - early_m1:+.1f} pp ({(late_m1 / early_m1 - 1) * 100:+.1f}% relative)")

fig, ax = plt.subplots(figsize=(14, 8))
sns.heatmap(retention.iloc[:, :13] * 100, annot=True, fmt=".0f", cmap="RdYlGn",
            vmin=0, vmax=40, cbar_kws={"label": "% of cohort active"},
            linewidths=.4, linecolor="white", annot_kws={"size": 8.5}, ax=ax)
ax.axhline(list(retention.index).index("2024-11"), color="black", lw=2.2)
ax.set_xlabel("Months since acquisition"); ax.set_ylabel("Acquisition cohort")
ax.set_title("Every cohort acquired from 2024-11 onward retains worse from M+1")
fig.savefig(FIG / "02_cohort_retention.png"); plt.close(fig)


# ===========================================================================
# 3. HIGH vs LOW REPEATER PROFILING
# ===========================================================================
log("\n" + "-" * 78)
log("3. SEGMENT PROFILING -- high repeaters vs one-and-done")
log("-" * 78)

users["segment"] = np.where(users.frequency >= 4, "High repeater (4+)",
                     np.where(users.frequency == 1, "One-and-done", "Low repeater (2-3)"))
hi = users[users.segment == "High repeater (4+)"]
lo = users[users.segment == "One-and-done"]

rows = []
for col in ["aov", "monetary", "total_tickets", "max_tickets", "return_rate",
            "discount_rate", "n_categories", "recency_days"]:
    a_, b_ = hi[col].dropna(), lo[col].dropna()
    t, p = stats.ttest_ind(a_, b_, equal_var=False)
    sp = np.sqrt(((len(a_) - 1) * a_.var() + (len(b_) - 1) * b_.var())
                 / (len(a_) + len(b_) - 2))
    rows.append({"feature": col, "high_repeater": round(a_.mean(), 3),
                 "one_and_done": round(b_.mean(), 3),
                 "diff": round(a_.mean() - b_.mean(), 3),
                 "cohens_d": round((a_.mean() - b_.mean()) / sp, 3),
                 "welch_t": round(t, 2), "p_value": p})
prof = pd.DataFrame(rows).sort_values("cohens_d", key=abs, ascending=False)
log("\n" + prof.to_string(index=False, float_format=lambda v: f"{v:.4g}"))
log("\nNOTE: n_categories and monetary are mechanically tied to order count "
    "(more orders -> more categories, more spend). They are descriptive only and "
    "are excluded from the causal read in Phase 3.")
prof.to_csv(TAB / "02_segment_profile.csv", index=False)

for col in ["primary_category", "channel"]:
    ct = pd.crosstab(users[col], users.segment, normalize="columns") * 100
    chi2, p, _, _ = stats.chi2_contingency(pd.crosstab(users[col], users.segment))
    log(f"\n--- {col} mix by segment (%), chi2 = {chi2:.1f}, p = {p:.3e} ---")
    log(ct.round(1).to_string())
    ct.to_csv(TAB / f"02_mix_{col}.csv")


# ===========================================================================
# 4. TIPPING POINTS
# ===========================================================================
log("\n" + "-" * 78)
log("4. TIPPING POINT DETECTION")
log("-" * 78)

# --- 4.1 Support contacts ----------------------------------------------------
tk = model.groupby("cs_tickets").agg(
    orders=("repeat_30d", "size"), repeat_30d=("repeat_30d", "mean"),
    aov=("order_amount", "mean")).query(f"orders >= {MIN_CELL}")
tk["repeat_30d"] = tk["repeat_30d"].round(4)
tk["delta_pp"] = (tk["repeat_30d"].diff() * 100).round(1)
log(f"\n--- 30-day repeat by cs_tickets (cells with >= {MIN_CELL} orders) ---")
log(tk.round(2).to_string())
tk.to_csv(TAB / "02_tipping_tickets.csv")

log("\nSplit-point scan (>=k vs <k):")
scan = []
for k in range(1, 6):
    a_ = model[model.cs_tickets < k]["repeat_30d"]
    b_ = model[model.cs_tickets >= k]["repeat_30d"]
    if len(b_) < 100:
        continue
    chi2, p, _, _ = stats.chi2_contingency(
        pd.crosstab(model.cs_tickets >= k, model.repeat_30d))
    d = b_.mean() - a_.mean()
    scan.append({"k": k, "n_below": len(a_), "rate_below": round(a_.mean(), 4),
                 "n_at_or_above": len(b_), "rate_at_or_above": round(b_.mean(), 4),
                 "delta_pp": round(d * 100, 1), "chi2": round(chi2, 1), "p": p})
    log(f"  k={k}: <k {pct(a_.mean())} (n={len(a_):,})  vs  >=k {pct(b_.mean())} "
        f"(n={len(b_):,})   delta={d * 100:+.1f} pp   chi2={chi2:.0f}   p={p:.2e}")
pd.DataFrame(scan).to_csv(TAB / "02_ticket_splitscan.csv", index=False)
best = max(scan, key=lambda r: abs(r["delta_pp"]))
log(f"\n  --> steepest break at cs_tickets >= {best['k']} "
    f"({best['delta_pp']:+.1f} pp, p = {best['p']:.2e}). "
    f"Marginal drop per ticket: 1st = {tk.loc[1, 'delta_pp']:+.1f} pp, "
    f"2nd = {tk.loc[2, 'delta_pp']:+.1f} pp, 3rd = {tk.loc[3, 'delta_pp']:+.1f} pp.")

# --- 4.2 Discount dependency, de-confounded ---------------------------------
# A one-order user who used a coupon has cum_discount_rate = 1.0 but is not
# "coupon dependent" -- they simply have no history. Restrict to users with a
# real history before banding, otherwise the top band is just one-and-dones.
log("\n--- Discount dependency ---")
naive = model.assign(band=pd.cut(model.cum_discount_rate, [-.01, .2, .4, .6, .8, 1.0],
                                 labels=["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]))
log("Naive banding over ALL orders (CONFOUNDED -- shown to document the trap):")
log(naive.groupby("band", observed=True).agg(
    orders=("repeat_30d", "size"), repeat=("repeat_30d", "mean"),
    avg_prior_orders=("cum_orders", "mean")).round(3).to_string())

deep = model[model.cum_orders >= 3].copy()
deep["band"] = pd.cut(deep.cum_discount_rate, [-.01, .2, .4, .6, .8, 1.0],
                      labels=["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"])
db = deep.groupby("band", observed=True).agg(
    orders=("repeat_30d", "size"), repeat_30d=("repeat_30d", "mean"),
    aov=("order_amount", "mean"), avg_prior_orders=("cum_orders", "mean"))
db["repeat_30d"] = db["repeat_30d"].round(4)
log(f"\nDe-confounded: users with >=3 prior orders only (n = {len(deep):,} orders)")
log(db.round(2).to_string())
db.to_csv(TAB / "02_tipping_discount.csv")

lo_d = deep[deep.cum_discount_rate <= 0.4]["repeat_30d"]
hi_d = deep[deep.cum_discount_rate >= 0.8]["repeat_30d"]
chi2, p_d, _, _ = stats.chi2_contingency(
    pd.crosstab(deep.cum_discount_rate >= 0.8, deep.repeat_30d))
log(f"\n  <=40% coupon history: {pct(lo_d.mean())} (n={len(lo_d):,})   "
    f">=80%: {pct(hi_d.mean())} (n={len(hi_d):,})   "
    f"delta = {(hi_d.mean() - lo_d.mean()) * 100:+.1f} pp, p = {p_d:.2e}")

# --- 4.3 Returns and category ------------------------------------------------
rt = model.groupby("is_returned").agg(
    orders=("repeat_30d", "size"), repeat_30d=("repeat_30d", "mean")).round(4)
log("\n--- Repeat by return flag ---")
log(rt.to_string())

cat = model.groupby("category").agg(
    orders=("repeat_30d", "size"), repeat_30d=("repeat_30d", "mean"),
    aov=("order_amount", "mean"), tickets=("cs_tickets", "mean"),
    return_rate=("is_returned", "mean")).round(4).sort_values("repeat_30d", ascending=False)
log("\n--- Repeat / ticket load by category ---")
log(cat.to_string())
cat.to_csv(TAB / "02_category_profile.csv")

# --- 4.4 Ticket load over time (root cause) ----------------------------------
om = orders["order_date"].dt.to_period("M").astype(str)
tick_trend = orders.groupby(om).agg(
    avg_tickets=("cs_tickets", "mean"),
    pct_1plus=("cs_tickets", lambda s: (s >= 1).mean()),
    pct_3plus=("cs_tickets", lambda s: (s >= 3).mean()),
    return_rate=("is_returned", "mean")).round(4)
tick_trend.index.name = "order_month"
log("\n--- Ticket load by month (suspected root cause) ---")
log(tick_trend.to_string())
tick_trend.to_csv(TAB / "02_ticket_trend.csv")

# Align on the shared index -- `view` stops one month earlier because of censoring.
common_idx = tick_trend.index.intersection(view.index)
r_new = np.corrcoef(tick_trend.loc[common_idx, "pct_1plus"],
                    view.loc[common_idx, "new_user_repeat"])[0, 1]
r_est = np.corrcoef(tick_trend.loc[common_idx, "pct_1plus"],
                    view.loc[common_idx, "established_repeat"])[0, 1]
log(f"\nMonthly correlation over {len(common_idx)} aligned months:")
log(f"  %orders with >=1 ticket  vs  new-user repeat     : r = {r_new:+.3f}")
log(f"  %orders with >=1 ticket  vs  established repeat  : r = {r_est:+.3f}")
log("  (n=17 months -- directional support for the mechanism, not proof. "
    "Phase 3 tests it at the order level with controls.)")

cat_tick = orders.assign(m=om).pivot_table(
    index="m", columns="category", values="cs_tickets", aggfunc="mean").round(3)
log("\n--- Avg tickets by category x month (where the strain landed) ---")
log(cat_tick.to_string())
cat_tick.to_csv(TAB / "02_ticket_by_category_month.csv")


# ===========================================================================
# 5. FIGURES
# ===========================================================================
fig, ax = plt.subplots(figsize=(13, 5.5))
xi = range(len(view))
ax.plot(xi, view.headline_repeat * 100, marker="", lw=2.6, color="#7f8c8d",
        label="Headline (all orders) -- what we report")
ax.plot(xi, view.new_user_repeat * 100, marker="o", lw=2.6, color="#c0392b",
        label="New-user 30d repeat -- survivorship-free")
ax.plot(xi, view.established_repeat * 100, marker="s", lw=2.2, ls="--", color="#2471a3",
        label="Established users (3+ prior orders)")
ax.axvline(list(view.index).index("2024-10") - .5, color="black", lw=1.4, ls=":")
ax.annotate("service strain begins",
            xy=(list(view.index).index("2024-10") - .35, 0.06),
            xycoords=("data", "axes fraction"),
            fontsize=10.5, style="italic", color="#333333")
ax.set_xticks(list(xi)); ax.set_xticklabels(view.index, rotation=45, ha="right")
ax.set_ylabel("30-day repeat rate (%)")
ax.set_title("The headline KPI hides the damage; new-user repeat does not")
ax.legend(frameon=False, fontsize=10.5, loc="center left")
fig.savefig(FIG / "02_repeat_trend.png"); plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
ax = axes[0]
bars = ax.bar(tk.index.astype(str), tk.repeat_30d * 100,
              color=["#3b7dd8" if i < 3 else "#c0392b" for i in tk.index])
ax.bar_label(bars, fmt="%.1f%%", fontsize=10)
ax.set_xlabel("Support contacts, trailing 30 days"); ax.set_ylabel("30-day repeat rate (%)")
ax.set_title("The cliff: repeat halves at the 3rd ticket")
ax = axes[1]
bars = ax.bar(db.index.astype(str), db.repeat_30d * 100, color="#8e6bbf")
ax.bar_label(bars, fmt="%.1f%%", fontsize=10)
ax.set_xlabel("Share of prior orders using a coupon")
ax.set_title("Coupon dependency (users with 3+ orders)")
plt.setp(axes[1].get_xticklabels(), rotation=20, ha="right")
fig.savefig(FIG / "02_tipping_points.png"); plt.close(fig)

fig, ax = plt.subplots(figsize=(13, 5))
ax2 = ax.twinx()
xi = range(len(common_idx))
ax.bar(xi, tick_trend.loc[common_idx, "pct_1plus"] * 100, color="#c0392b", alpha=.7,
       label="% orders with >=1 ticket")
ax2.plot(xi, view.loc[common_idx, "new_user_repeat"] * 100, color="#1b3b6f",
         marker="o", lw=2.6, label="New-user 30d repeat")
ax.set_xticks(list(xi)); ax.set_xticklabels(common_idx, rotation=45, ha="right")
ax.set_ylabel("% orders with >=1 ticket", color="#c0392b")
ax2.set_ylabel("New-user 30d repeat (%)", color="#1b3b6f")
ax.set_title(f"Ticket load vs new-user repeat, r = {r_new:+.2f}")
ax.grid(False); ax2.grid(False)
fig.savefig(FIG / "02_tickets_vs_repeat.png"); plt.close(fig)

# Category x ticket band, with small cells suppressed
cnt = model.groupby(["category", "ticket_band"], observed=True)["repeat_30d"].size().unstack()
cd = model.groupby(["category", "ticket_band"], observed=True)["repeat_30d"].mean().unstack() * 100
cd = cd.where(cnt >= MIN_CELL)
cd = cd.reindex([c for c in CATEGORY_ORDER if c in cd.index])
fig, ax = plt.subplots(figsize=(11, 5.5))
cd.plot(kind="bar", ax=ax, width=.8, colormap="RdYlBu_r")
ax.set_ylabel("30-day repeat rate (%)"); ax.set_xlabel("")
ax.set_title("The ticket gradient holds inside every category")
ax.legend(title="tickets", frameon=False, ncol=4, fontsize=10)
plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
fig.savefig(FIG / "02_category_ticket_interaction.png"); plt.close(fig)
log(f"\n--- Repeat by category x ticket band (%), cells with <{MIN_CELL} orders suppressed ---")
log(cd.round(1).to_string())
log("\nSupporting cell counts:")
log(cnt.reindex(cd.index).to_string())
cd.to_csv(TAB / "02_category_ticket_band.csv")

log.save()
