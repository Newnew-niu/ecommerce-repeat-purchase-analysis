"""
Phase 5 -- KPI dictionary values, customer-level comparisons, robustness checks.

Reads  : data/processed/{orders_clean,user_features,order_model_table}.csv
Writes : outputs/tables/05_*.csv, outputs/figures/05_*.png, logs/05_kpi_log.txt

Phases 1-4 answer "why did repeat purchase decline?". This phase adds what a
reviewer would ask next:
  1. One table of KPIs with explicit numerator / denominator / window, computed
     by src/kpis.py -- the same module the dashboard uses.
  2. First-time vs repeat orders and customers (where does GMV come from?).
  3. Time to second purchase.
  4. Robustness: does the new-customer decline survive a 60- or 90-day window
     instead of 30? Does the ticket cliff survive dropping imputed ticket values?
     Does the headline p-value survive user-clustered standard errors?
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.formula.api as smf
from statsmodels.stats.proportion import proportions_ztest, proportion_confint

from common import PROC, FIG, TAB, LOGS, SNAPSHOT, Tee, pct, usd
import kpis

log = Tee(LOGS / "05_kpi_log.txt")
plt.rcParams.update({
    "figure.dpi": 120, "savefig.bbox": "tight", "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#c3c2b7", "axes.labelcolor": "#52514e",
    "xtick.color": "#52514e", "ytick.color": "#52514e", "font.size": 11,
})
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#898781"

orders = kpis.load_orders()
users = pd.read_csv(PROC / "user_features.csv")

log("=" * 78)
log("PHASE 5 -- KPI DICTIONARY, CUSTOMER COMPARISONS, ROBUSTNESS")
log("=" * 78)

# Baseline vs recent, matching the quarters used in Phase 2.
# Order-level KPIs are split on ORDER date; customer-level KPIs on FIRST-ORDER date.
PERIODS = {
    "Baseline (2024Q2-Q3)": ("2024-04-01", "2024-09-30"),
    "Recent (2025Q1-Q2)": ("2025-01-01", "2025-06-30"),
}


def in_range(s, lo, hi):
    return (s >= pd.Timestamp(lo)) & (s < pd.Timestamp(hi) + pd.Timedelta(days=1))


# ===========================================================================
# 1. KPI TABLE
# ===========================================================================
log("\n" + "-" * 78)
log("1. KPI TABLE (definitions in docs/kpi_definitions.md)")
log("-" * 78)

firsts = kpis.first_orders(orders)
# scope -> (orders for order-level KPIs, orders of customers acquired in scope)
scopes = {"Full period (2024-01..2025-06)": (orders, orders)}
for lbl, (lo, hi) in PERIODS.items():
    acq = set(firsts.loc[in_range(firsts.order_date, lo, hi), "user_id"])
    scopes[lbl] = (orders[in_range(orders.order_date, lo, hi)],
                   orders[orders.user_id.isin(acq)])

rows = []
for scope, (o_level, c_level) in scopes.items():
    s_o = kpis.kpi_snapshot(o_level)
    s_c = kpis.kpi_snapshot(c_level)
    rows += [(scope,) + r for r in [
        ("Orders", "count", s_o["orders"], "", "", "order"),
        ("Active customers", "count", s_o["customers"], "", "", "customer"),
        ("GMV", "usd", s_o["gmv"], "", "", "order"),
        ("Average order value (AOV)", "usd", s_o["aov"], s_o["gmv"], s_o["orders"], "order"),
        ("Purchase frequency (orders / active customer)", "ratio",
         s_o["purchase_frequency"], s_o["orders"], s_o["customers"], "customer"),
        ("Order-level 30-day repeat rate (headline)", "rate", s_o["order_repeat_30d"],
         s_o["order_repeat_30d_num"], s_o["order_repeat_30d_den"], "order"),
        ("New-customer 30-day repeat rate", "rate", s_c["new_customer_repeat_30d"],
         s_c["new_customer_repeat_30d_num"], s_c["new_customer_repeat_30d_den"], "new customer"),
        ("90-day repeat customer rate", "rate", s_c["repeat_customer_90d"],
         s_c["repeat_customer_90d_num"], s_c["repeat_customer_90d_den"], "new customer"),
        ("Median days to 2nd order (repeaters only)", "days", s_c["median_days_to_2nd"],
         "", "", "repeating customer"),
    ]]

kpi_tab = pd.DataFrame(rows, columns=["scope", "kpi", "unit", "value", "numerator",
                                      "denominator", "counting_unit"])
kpi_tab["value"] = kpi_tab["value"].astype(float).round(4)
log("\n" + kpi_tab.to_string(index=False))
kpi_tab.to_csv(TAB / "05_kpi_summary.csv", index=False)

ret = kpis.cohort_retention(orders)
m1 = ret[1].dropna() * 100
log(f"\nCohort M+1 retention: 2024-01..09 mean {m1.loc['2024-01':'2024-09'].mean():.1f}%, "
    f"2024-11..2025-05 mean {m1.loc['2024-11':'2025-05'].mean():.1f}% "
    f"(unweighted mean of cohort rates, as in Phase 2)")

log("\nNOTE: the 90-day repeat customer rate for 'Recent' only includes customers "
    "acquired by 2025-04-01 (90 days of observation needed); the 30-day rate "
    "includes those acquired by 2025-05-31. Windows are never compared across "
    "unequal observation periods.")


# ===========================================================================
# 2. FIRST-TIME vs REPEAT
# ===========================================================================
log("\n" + "-" * 78)
log("2. FIRST-TIME vs REPEAT ORDERS AND CUSTOMERS")
log("-" * 78)

fvr = kpis.first_vs_repeat_orders(orders).round(4)
log("\n" + fvr.to_string())
fvr.to_csv(TAB / "05_first_vs_repeat_orders.csv")

users["customer_type"] = np.where(users.frequency >= 2, "Repeat customer (2+ orders)",
                                  "One-time customer")
cvr = users.groupby("customer_type").agg(
    customers=("user_id", "size"), gmv=("monetary", "sum"),
    avg_orders=("frequency", "mean"), avg_aov=("aov", "mean"),
    avg_lifetime_gmv=("monetary", "mean"))
cvr["customer_share"] = cvr.customers / cvr.customers.sum()
cvr["gmv_share"] = cvr.gmv / cvr.gmv.sum()
cvr = cvr.round(4)
log("\n" + cvr.to_string())
cvr.to_csv(TAB / "05_customer_type_comparison.csv")
rep = cvr.loc["Repeat customer (2+ orders)"]
log(f"\n>>> Repeat customers are {pct(rep.customer_share)} of customers but "
    f"{pct(rep.gmv_share)} of GMV. Their AOV is LOWER than one-time customers' "
    f"(${rep.avg_aov:,.2f} vs ${cvr.loc['One-time customer', 'avg_aov']:,.2f}) -- "
    f"their value comes from frequency, not basket size.")
log("CAVEAT: 'ever ordered twice' is tenure-biased -- customers acquired in 2025 "
    "have had less time to reorder. Used here for GMV attribution only; trend "
    "comparisons use the fixed-window metrics in section 1.")

seg = users.groupby("rfm_segment").agg(customers=("user_id", "size"),
                                       gmv=("monetary", "sum"))
seg["customer_share"] = seg.customers / seg.customers.sum()
seg["gmv_share"] = seg.gmv / seg.gmv.sum()
seg = seg.sort_values("gmv", ascending=False).round(4)
log("\n--- GMV by RFM segment ---")
log(seg.to_string())
seg.to_csv(TAB / "05_rfm_revenue.csv")


# ===========================================================================
# 3. TIME TO SECOND ORDER
# ===========================================================================
log("\n" + "-" * 78)
log("3. TIME TO SECOND ORDER")
log("-" * 78)

# Comparable observation: only customers acquired >= 180 days before snapshot,
# and only second orders within 180 days, so recent cohorts are not truncated
# differently from old ones.
H = 180
f = firsts[firsts.order_date <= SNAPSHOT - pd.Timedelta(days=H)].copy()
f["second_within_h"] = f.days_to_next <= H
tts = f.loc[f.second_within_h, "days_to_next"]
log(f"Customers acquired <= {(SNAPSHOT - pd.Timedelta(days=H)).date()}: {len(f):,}; "
    f"{pct(f.second_within_h.mean())} placed a 2nd order within {H} days.")
q = tts.quantile([.25, .5, .75, .9])
log(f"Among them, days to 2nd order: p25 {q[.25]:.0f}, median {q[.5]:.0f}, "
    f"p75 {q[.75]:.0f}, p90 {q[.9]:.0f}")
share_30 = (tts <= 30).mean()
log(f"{pct(share_30)} of 2nd orders placed within {H} days arrive within 30 days.")
log("CAVEAT: on this SIMULATED data the break at day 30 is partly built in -- "
    "00_make_dataset.py draws 'repeat within 30 days' gaps from a 1-30 day "
    "distribution. So this chart illustrates the method; it does not independently "
    "validate the 30-day window. On real data, pick the window from this "
    "distribution (and see the 60/90-day sensitivity in section 4.1).")

bins = list(range(0, H + 1, 15))
hist = pd.cut(tts, bins=bins, right=True, include_lowest=True).value_counts().sort_index()
hist_tab = pd.DataFrame({"days_from": bins[:-1], "days_to": bins[1:],
                         "customers": hist.values})
hist_tab["share"] = (hist_tab.customers / hist_tab.customers.sum()).round(4)
hist_tab.to_csv(TAB / "05_time_to_second_order.csv", index=False)

fig, ax = plt.subplots(figsize=(10, 4.6))
cols = [BLUE if b < 30 else "#9ec5f4" for b in hist_tab.days_from]
ax.bar(hist_tab.days_from + 7.5, hist_tab.customers, width=13.5, color=cols)
ax.axvline(30, color="#52514e", lw=1, ls="--")
ax.text(31.5, hist_tab.customers.max() * 0.95, "30-day KPI window", color="#52514e",
        fontsize=10)
ax.set_xlabel("Days from first to second order")
ax.set_ylabel("Customers")
ax.set_title(f"Most second orders arrive within 30 days "
             f"({pct(share_30, 0)} of those within {H} days)", loc="left")
ax.grid(axis="y", color="#e1e0d9", lw=0.8); ax.set_axisbelow(True)
fig.savefig(FIG / "05_time_to_second_order.png"); plt.close(fig)


# ===========================================================================
# 4. ROBUSTNESS
# ===========================================================================
log("\n" + "-" * 78)
log("4. ROBUSTNESS CHECKS")
log("-" * 78)

# --- 4.1 Window sensitivity on a FIXED population -----------------------------
# Recent cohorts end 2025-03-31 so every customer has >= 90 days of observation;
# the same customers are scored under all three windows.
BASE = ("2024-04-01", "2024-09-30")
RECENT = ("2024-11-01", "2025-03-31")
fb = firsts[in_range(firsts.order_date, *BASE)]
fr = firsts[in_range(firsts.order_date, *RECENT)]
sens_rows = []
for w in (30, 60, 90):
    xb, xr = int((fb.days_to_next <= w).sum()), int((fr.days_to_next <= w).sum())
    z, p = proportions_ztest([xr, xb], [len(fr), len(fb)])
    lo_b, hi_b = proportion_confint(xb, len(fb), method="wilson")
    lo_r, hi_r = proportion_confint(xr, len(fr), method="wilson")
    sens_rows.append({
        "window_days": w, "baseline_n": len(fb), "baseline_rate": xb / len(fb),
        "baseline_ci_low": lo_b, "baseline_ci_high": hi_b,
        "recent_n": len(fr), "recent_rate": xr / len(fr),
        "recent_ci_low": lo_r, "recent_ci_high": hi_r,
        "delta_pp": (xr / len(fr) - xb / len(fb)) * 100,
        "relative_change": (xr / len(fr)) / (xb / len(fb)) - 1, "z": z, "p_value": p,
    })
sens = pd.DataFrame(sens_rows)
log(f"\n4.1 New-customer repeat by window. Baseline cohorts {BASE[0]}..{BASE[1]} "
    f"(n={len(fb):,}), recent cohorts {RECENT[0]}..{RECENT[1]} (n={len(fr):,}). "
    f"Same customers under every window.")
log(sens.to_string(index=False, float_format=lambda v: f"{v:.4g}"))
sens.to_csv(TAB / "05_window_sensitivity.csv", index=False)
log(">>> The decline is not an artefact of the 30-day choice: it is present and "
    "significant at every window tested." if (sens.delta_pp < 0).all()
    and (sens.p_value < 0.01).all() else
    ">>> WARNING: the decline is not consistent across windows -- see table.")

fig, ax = plt.subplots(figsize=(9, 4.6))
x = np.arange(len(sens)); wdt = 0.36
for off, col, key, lbl in [(-wdt / 2, BLUE, "baseline", "Baseline cohorts (2024-04..09)"),
                           (wdt / 2, ORANGE, "recent", "Recent cohorts (2024-11..2025-03)")]:
    r = sens[f"{key}_rate"] * 100
    err = [r - sens[f"{key}_ci_low"] * 100, sens[f"{key}_ci_high"] * 100 - r]
    b = ax.bar(x + off, r, wdt * 0.94, color=col, label=lbl, yerr=err,
               error_kw={"ecolor": "#52514e", "elinewidth": 1, "capsize": 3})
    ax.bar_label(b, fmt="%.1f%%", padding=6, fontsize=10, color="#0b0b0b")
ax.set_xticks(x, [f"{w}-day window" for w in sens.window_days])
ax.set_ylabel("New customers who reorder (%)")
ax.set_ylim(0, sens[["baseline_ci_high", "recent_ci_high"]].max().max() * 118)
ax.set_title("The new-customer decline holds at 30, 60 and 90 days", loc="left")
ax.legend(frameon=False, loc="upper left", fontsize=10)
ax.grid(axis="y", color="#e1e0d9", lw=0.8); ax.set_axisbelow(True)
fig.savefig(FIG / "05_window_sensitivity.png"); plt.close(fig)

# --- 4.2 Ticket cliff without imputed ticket values ---------------------------
model = pd.read_csv(PROC / "order_model_table.csv", parse_dates=["order_date"])
model = model.merge(orders[["order_id", "cs_tickets_imputed"]], on="order_id", how="left")
both = []
for lbl, d in [("all scoreable orders", model),
               ("excluding imputed cs_tickets", model[model.cs_tickets_imputed == 0])]:
    t = d.assign(band=np.minimum(d.cs_tickets, 3)).groupby("band")["repeat_30d"].agg(
        ["size", "mean"])
    t.index = ["0", "1", "2", "3+"]
    t.columns = [f"orders ({lbl})", f"repeat ({lbl})"]
    both.append(t)
tick_rb = pd.concat(both, axis=1).round(4)
n_imp = int(model.cs_tickets_imputed.sum())
log(f"\n4.2 Ticket gradient with and without the {n_imp:,} scoreable orders whose "
    f"cs_tickets was imputed from the -1 sentinel:")
log(tick_rb.to_string())
tick_rb.to_csv(TAB / "05_ticket_robustness.csv")

# --- 4.3 Headline test with user-clustered SEs --------------------------------
model["quarter"] = model.order_date.dt.to_period("Q").astype(str)
sub = model[model.quarter.isin(["2024Q2", "2024Q3", "2025Q1", "2025Q2"])].copy()
sub["recent"] = sub.quarter.isin(["2025Q1", "2025Q2"]).astype(int)
naive = smf.logit("repeat_30d ~ recent", data=sub).fit(disp=0)
clus = smf.logit("repeat_30d ~ recent", data=sub).fit(
    disp=0, cov_type="cluster", cov_kwds={"groups": sub["user_id"]})
log(f"\n4.3 Headline (order-level) decline, recent vs baseline quarters:")
log(f"  naive SE p = {naive.pvalues['recent']:.2e}   "
    f"user-clustered SE p = {clus.pvalues['recent']:.2e}")
log("  Phase 2's chi-square treats orders as independent; clustering on user_id "
    "is the correct test for an order-level metric. New-customer tests are "
    "unaffected (one row per customer).")
pd.DataFrame([{"test": "headline repeat, recent vs baseline",
               "p_naive": naive.pvalues["recent"],
               "p_user_clustered": clus.pvalues["recent"]}]).to_csv(
    TAB / "05_headline_clustered_test.csv", index=False)

log.save()
