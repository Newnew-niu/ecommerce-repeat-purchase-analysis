"""
Phase 4 -- Intervention design and ROI quantification.

Reads  : data/processed/{order_model_table,user_features}.csv,
         outputs/tables/03_{ticket_pdp,category_counterfactual,marginal_effects}.csv
Writes : outputs/tables/04_*.csv, outputs/figures/04_*.png, logs/04_roi_log.txt

SIZING DISCIPLINE
  1. Addressable population is an ACTUAL COUNT from the baseline quarter,
     annualised x4 and scaled by SAMPLE_RATE. Never a hand-waved "% of base".
  2. Value per incremental repeat is computed from the AOV OF THE ADDRESSED ROWS,
     not the blended AOV. Electronics orders are worth ~3x a Grocery order; using
     one blended figure would misprice every targeted initiative.
  3. Effect size comes from the Phase 3 MODEL counterfactual (which nets out
     selection), then takes a realisation haircut < 1.
  4. Hard cost-to-serve savings (ticket handling, reverse logistics) are counted
     separately from revenue effects and clearly labelled.
  5. Every initiative faces a BREAK-EVEN GATE. Anything that fails is reported as
     failing and is not recommended for funding. The gate is computed, not asserted.
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from common import PROC, FIG, TAB, LOGS, GROSS_MARGIN, Tee, pct, usd

log = Tee(LOGS / "04_roi_log.txt")
sns.set_theme(style="whitegrid", context="talk")
plt.rcParams["figure.dpi"] = 120
plt.rcParams["savefig.bbox"] = "tight"
plt.rcParams["axes.titleweight"] = "bold"

# The analysis extract is a 10% random user sample -- standard practice for
# keeping an exploratory pull tractable. All population counts are grossed up by
# this factor; all RATES are unaffected. Stated explicitly because every absolute
# dollar figure below depends on it.
SAMPLE_RATE = 0.10
SCALE = 1.0 / SAMPLE_RATE
ANNUALISE = 4.0

# Fully-loaded cost of handling one support contact (agent time, tooling, QA).
TICKET_HANDLING_COST = 6.00

model = pd.read_csv(PROC / "order_model_table.csv", parse_dates=["order_date"])
users = pd.read_csv(PROC / "user_features.csv", parse_dates=["first_order", "last_order"])
pdp = pd.read_csv(TAB / "03_ticket_pdp.csv")
catcf = pd.read_csv(TAB / "03_category_counterfactual.csv")

log("=" * 78)
log("PHASE 4 -- BUSINESS CASE")
log("=" * 78)


# ===========================================================================
# 0. RUN-RATE BASELINE
# ===========================================================================
model["quarter"] = model["order_date"].dt.to_period("Q").astype(str)
q = model[model.quarter == "2025Q1"]          # last complete, fully-scoreable qtr

aov_blend = q.order_amount.mean()
gmv_yr = q.order_amount.sum() * ANNUALISE * SCALE

log(f"\nBaseline quarter: 2025Q1 (last complete quarter clear of the 30-day "
    f"censoring window)")
log(f"  scoreable orders in extract   {len(q):,}")
log(f"  extract is a {pct(SAMPLE_RATE, 0)} user sample -> gross-up factor x{SCALE:.0f}")
log(f"  implied annual GMV            {usd(gmv_yr)}")
log(f"  implied annual contribution   {usd(gmv_yr * GROSS_MARGIN)} "
    f"(at {pct(GROSS_MARGIN)} margin)")
log(f"  blended AOV                   ${aov_blend:,.2f}")
log(f"  30-day repeat                 {pct(q.repeat_30d.mean())}")

# --- Downstream value of one incremental repeat ------------------------------
seq = model.groupby("cum_orders")["repeat_30d"].agg(["size", "mean"])
log("\n--- Observed continuation rate by lifecycle depth ---")
log(seq.head(8).round(4).to_string())

cont = seq["mean"].reindex(range(0, 9)).ffill().values
chain, survivor = 0.0, 1.0
for k in range(1, 9):
    survivor *= cont[min(k, len(cont) - 1)]
    chain += survivor
LTV_MULT = 1.0 + chain
log(f"\nDownstream multiplier: one incremental repeat is worth {LTV_MULT:.2f} orders "
    f"in expectation (itself + {chain:.2f} follow-ons from the OBSERVED "
    f"continuation chain, capped at 8 steps). Capped and observation-based, so it "
    f"understates rather than flatters.")


def value_per_repeat(aov_segment):
    """Contribution value of one incremental repeat order in a given segment."""
    return aov_segment * LTV_MULT * GROSS_MARGIN


log(f"\nValue of one incremental repeat, by segment AOV "
    f"(blended = 2025Q1; categories = full-period AOV, illustrative):")
cat_aov = model.groupby("category")["order_amount"].mean()
for lbl, a in [("blended", aov_blend)] + [(c, cat_aov[c]) for c in
                                          ("Electronics", "Home", "Grocery")]:
    log(f"  {lbl:<14} AOV ${a:>7,.2f} -> ${value_per_repeat(a):>7,.2f} per repeat")
log("Targeting where AOV is high is not a detail -- it is most of the business case.")


# ===========================================================================
# HELPER
# ===========================================================================
def business_case(name, tier, addressable_q, uplift_pp, realisation,
                  cost_per_unit, fixed_cost=0.0, tickets_avoided_per_unit=0.0,
                  other_savings_per_unit=0.0):
    """Annualised case for one intervention, priced on the addressed rows' own AOV."""
    pop_q = len(addressable_q)
    pop_y = pop_q * ANNUALISE * SCALE
    seg_aov = addressable_q.order_amount.mean()
    vpr = value_per_repeat(seg_aov)

    eff = uplift_pp / 100 * realisation
    incr_repeats = pop_y * eff
    incr_gmv = incr_repeats * seg_aov * LTV_MULT
    revenue_contrib = incr_repeats * vpr
    cost_avoided = pop_y * (tickets_avoided_per_unit * TICKET_HANDLING_COST
                            + other_savings_per_unit)
    total_benefit = revenue_contrib + cost_avoided

    cost = pop_y * cost_per_unit + fixed_cost
    net = total_benefit - cost
    # Break-even: uplift needed for revenue alone to cover cost net of savings
    be_pp = (cost - cost_avoided) / (pop_y * vpr) * 100 if pop_y else np.nan

    return {
        "intervention": name, "tier": tier,
        "addressable_yr": int(pop_y),
        "segment_aov": round(seg_aov, 2),
        "value_per_repeat": round(vpr, 2),
        "modelled_uplift_pp": round(uplift_pp, 2),
        "realisation": realisation,
        "effective_uplift_pp": round(eff * 100, 2),
        "incremental_repeats_yr": int(round(incr_repeats)),
        "incremental_gmv_yr": round(incr_gmv, 0),
        "revenue_contribution_yr": round(revenue_contrib, 0),
        "cost_avoided_yr": round(cost_avoided, 0),
        "total_benefit_yr": round(total_benefit, 0),
        "cost_yr": round(cost, 0),
        "net_yr": round(net, 0),
        "roi": round(net / cost, 2) if cost > 0 else np.nan,
        "breakeven_uplift_pp": round(be_pp, 2),
        "clears_gate": bool(eff * 100 > be_pp),
    }


pdp_i = pdp.set_index("cs_tickets")["predicted_repeat"]
up_2_to_1 = (pdp_i[1] - pdp_i[2]) * 100
up_3_to_1 = (pdp_i[1] - pdp_i[3]) * 100


# ===========================================================================
# INITIATIVE 1 -- TIERED SERVICE RECOVERY
# ===========================================================================
log("\n" + "=" * 78)
log("INITIATIVE 1 -- Tiered service recovery before the cliff")
log("=" * 78)

t2 = q[q.cs_tickets == 2]
t3 = q[q.cs_tickets >= 3]
log(f"\nAddressable in 2025Q1 extract: {len(t2):,} orders at exactly 2 tickets, "
    f"{len(t3):,} at 3+. Grossed up: {len(t2) * ANNUALISE * SCALE:,.0f} and "
    f"{len(t3) * ANNUALISE * SCALE:,.0f} cases/yr.")
log(f"  AOV of 2-ticket orders  ${t2.order_amount.mean():,.2f}")
log(f"  AOV of 3+-ticket orders ${t3.order_amount.mean():,.2f}")
log(f"  (both well above the ${aov_blend:,.2f} blended AOV -- complaints "
    f"concentrate in expensive baskets, which is what makes this worth doing)")
log(f"\nModel counterfactual: 2 tickets -> 1 is worth {up_2_to_1:+.1f} pp, "
    f"3 tickets -> 1 is worth {up_3_to_1:+.1f} pp.")
log("The raw observational 2->3 gap is ~18 pp. Not used: it embeds selection "
    "(customers already leaving complain more on the way out).")

log("\nCOST DESIGN -- this is where the initiative lives or dies. A human callback "
    "is fully loaded at ~$9-14. Tier A's modelled uplift cannot cover that, so "
    "Tier A must be automated. Tier B's 16.8 pp can. The tiering is not a "
    "presentation choice, it falls out of the break-even arithmetic.")

cases = []
for real, lbl in [(0.35, "conservative"), (0.50, "base"), (0.65, "optimistic")]:
    cases.append(business_case(
        "1. Tiered service recovery", f"A: automated, 2 tickets ({lbl})",
        t2, up_2_to_1, real, cost_per_unit=0.80, fixed_cost=25_000,
        tickets_avoided_per_unit=0.45))
    cases.append(business_case(
        "1. Tiered service recovery", f"B: human callback, 3+ tickets ({lbl})",
        t3, up_3_to_1, real, cost_per_unit=9.00, fixed_cost=20_000,
        tickets_avoided_per_unit=1.10))

log("\nTier A: automated apology + priority re-routing + service credit, $0.80/case, "
    "$25k build. Assumes 0.45 downstream contacts avoided per case.")
log("Tier B: senior-agent callback for escalated cases, $9.00/case, $20k setup. "
    "Assumes 1.10 downstream contacts avoided per case.")


# ===========================================================================
# INITIATIVE 2 -- ELECTRONICS / HOME POST-PURCHASE FIX
# ===========================================================================
log("\n" + "=" * 78)
log("INITIATIVE 2 -- Fix the Electronics & Home post-purchase experience")
log("=" * 78)

TARGET = ["Electronics", "Home"]
qc = q[q.category.isin(TARGET)]
cf_t = catcf[catcf.category.isin(TARGET)]
w_uplift = float(np.average(cf_t.uplift_pp, weights=cf_t.orders))

log("\n" + model[model.category.isin(TARGET + ["Grocery", "Beauty"])]
    .groupby("category")
    .agg(orders=("repeat_30d", "size"), repeat=("repeat_30d", "mean"),
         tickets=("cs_tickets", "mean"), aov=("order_amount", "mean"),
         returns=("is_returned", "mean")).round(3).to_string())
log(f"\nElectronics + Home: {pct(len(qc) / len(q))} of orders, "
    f"${qc.order_amount.mean():,.2f} AOV, and the two worst repeat rates.")
log(f"Model counterfactual -- zeroing support contacts in these categories is "
    f"worth {w_uplift:.2f} pp of repeat (order-weighted). That is the CEILING for "
    f"a fix that only addresses contacts.")
log("Phase 2 root cause: Electronics avg tickets 0.24 -> 0.69 and Home 0.25 -> 0.42 "
    "between 2024-01 and 2025-06. Fulfilment and product-information problem, not "
    "a contact-centre capacity problem.")

avg_tickets_target = qc.cs_tickets.mean()
log(f"\nCost-to-serve today: {avg_tickets_target:.3f} tickets/order x "
    f"${TICKET_HANDLING_COST:.2f} = ${avg_tickets_target * TICKET_HANDLING_COST:.2f} "
    f"per order. A 30% reduction is assumed, i.e. "
    f"{avg_tickets_target * 0.30:.3f} contacts avoided per order.")

for real, lbl in [(0.40, "conservative"), (0.60, "base"), (0.80, "optimistic")]:
    cases.append(business_case(
        "2. Electronics/Home post-purchase fix", lbl, qc, w_uplift, real,
        cost_per_unit=0.25, fixed_cost=150_000,
        tickets_avoided_per_unit=avg_tickets_target * 0.30,
        other_savings_per_unit=0.35))     # reverse-logistics saving

log("\nUnit cost $0.25/order (proactive delivery comms + spec-content remediation, "
    "amortised), $150k fixed (content rebuild, inbound QC sampling programme). "
    "Plus $0.35/order assumed reverse-logistics saving from better expectations.")


# ===========================================================================
# INITIATIVE 3 -- COUPON DEPENDENCY
# ===========================================================================
log("\n" + "=" * 78)
log("INITIATIVE 3 -- Wean the coupon-dependent segment")
log("=" * 78)

deep = model[model.cum_orders >= 3]
dep = deep[deep.cum_discount_rate >= 0.6]
indep = deep[deep.cum_discount_rate <= 0.4]
gap = (indep.repeat_30d.mean() - dep.repeat_30d.mean()) * 100
q_dep = q[(q.cum_orders >= 3) & (q.cum_discount_rate >= 0.6)]

log(f"\nAmong users with >=3 prior orders:")
log(f"  coupon-independent (<=40% discounted): {pct(indep.repeat_30d.mean())} "
    f"repeat, n = {len(indep):,}")
log(f"  coupon-dependent   (>=60% discounted): {pct(dep.repeat_30d.mean())} "
    f"repeat, n = {len(dep):,}")
log(f"  observational gap: {gap:.1f} pp")
log(f"  addressable: {len(q_dep):,} orders in 2025Q1 extract -> "
    f"{len(q_dep) * ANNUALISE * SCALE:,.0f}/yr")

# pp per 1.0 dependency. Read from Phase 3 rather than typed in; rounded to the
# 2 dp published in REPORT.md so the business case is reproducible to the dollar.
AME_DISC_DEP = round(-float(pd.read_csv(TAB / "03_marginal_effects.csv", index_col=0)
                            .loc["disc_dep_c", "dy_dx_pp"]), 2)
SHIFT = 0.25
uplift3 = AME_DISC_DEP * SHIFT
log(f"\nPlanning number: Phase 3 AME is {AME_DISC_DEP:.1f} pp per full unit of "
    f"dependency. A realistic programme shifts a user's coupon rate by ~{SHIFT:.2f}, "
    f"giving {uplift3:.1f} pp -- deliberately below the {gap:.1f} pp observational gap.")
log("\nREVERSE CAUSALITY WARNING: low-intent users seek coupons, so an unknown part "
    "of the observational gap is selection running backwards. Of the three "
    "initiatives this has the weakest causal identification. It is therefore "
    "specified as a randomised holdout test, not a rollout.")

coupon_value = aov_blend * 0.12
margin_saved = coupon_value * SHIFT * 0.5
log(f"\nUnit economics: avg coupon ~{pct(0.12, 0)} of AOV = ${coupon_value:.2f}. "
    f"Cutting dependency {SHIFT:.2f} with half sticking recovers "
    f"${margin_saved:.2f}/order in margin, against $0.90/order CRM cost.")

for real, lbl in [(0.30, "conservative"), (0.50, "base"), (0.70, "optimistic")]:
    cases.append(business_case(
        "3. Coupon-dependency weaning", lbl, q_dep, uplift3, real,
        cost_per_unit=0.90, fixed_cost=35_000,
        other_savings_per_unit=margin_saved))


# ===========================================================================
# CONSOLIDATE
# ===========================================================================
allc = pd.DataFrame(cases)
allc.to_csv(TAB / "04_business_cases.csv", index=False)

log("\n" + "=" * 78)
log("CONSOLIDATED BUSINESS CASE (annualised, contribution margin)")
log("=" * 78)
show = allc[["intervention", "tier", "addressable_yr", "segment_aov",
             "effective_uplift_pp", "incremental_repeats_yr", "incremental_gmv_yr",
             "revenue_contribution_yr", "cost_avoided_yr", "cost_yr", "net_yr",
             "roi", "breakeven_uplift_pp", "clears_gate"]]
log("\n" + show.to_string(index=False))

base = allc[allc.tier.str.contains("base")].copy()
log("\n--- BASE CASE ---")
for _, r in base.iterrows():
    flag = "PASS" if r.clears_gate else "FAIL"
    log(f"  [{flag}] {r.intervention:<40} {r.tier:<32} "
        f"net {usd(r.net_yr):>10}  ROI {r.roi:>6.2f}x  "
        f"(needs {r.breakeven_uplift_pp:.2f} pp, delivers {r.effective_uplift_pp:.2f} pp)")

passing = base[base.clears_gate]
failing = base[~base.clears_gate]

tot_gmv = passing.incremental_gmv_yr.sum()
tot_ben = passing.total_benefit_yr.sum()
tot_cost = passing.cost_yr.sum()
tot_net = passing.net_yr.sum()

log(f"\n--- RECOMMENDED PORTFOLIO (initiatives clearing the break-even gate) ---")
log(f"  {'incremental GMV':<34} {usd(tot_gmv):>12}")
log(f"  {'revenue contribution':<34} {usd(passing.revenue_contribution_yr.sum()):>12}")
log(f"  {'cost-to-serve avoided':<34} {usd(passing.cost_avoided_yr.sum()):>12}")
log(f"  {'total benefit':<34} {usd(tot_ben):>12}")
log(f"  {'programme cost':<34} {usd(tot_cost):>12}")
log(f"  {'NET CONTRIBUTION':<34} {usd(tot_net):>12}")
log(f"  {'NET ROI':<34} {tot_net / tot_cost:>11.2f}x")
log(f"  {'incremental repeat orders/yr':<34} {passing.incremental_repeats_yr.sum():>12,}")

if len(failing):
    log(f"\n--- NOT RECOMMENDED FOR FUNDING (fails break-even at base case) ---")
    for _, r in failing.iterrows():
        log(f"  {r.intervention} / {r.tier}: needs {r.breakeven_uplift_pp:.2f} pp, "
            f"model supports {r.effective_uplift_pp:.2f} pp -> net {usd(r.net_yr)}")
    log("  These are reported, not buried. Funding them would destroy value at the "
        "modelled effect sizes.")

for lbl in ["conservative", "optimistic"]:
    sub = allc[allc.tier.str.contains(lbl)]
    sub_p = sub[sub.clears_gate]
    log(f"\n  {lbl.capitalize()} case (gate-clearing only): net "
        f"{usd(sub_p.net_yr.sum())} across {len(sub_p)} initiatives")

log(f"\n  Scale check: recommended incremental GMV is {pct(tot_gmv / gmv_yr)} of the "
    f"{usd(gmv_yr)} annual run-rate, and net contribution is "
    f"{pct(tot_net / (gmv_yr * GROSS_MARGIN))} of annual contribution. "
    f"Retention programmes that claim more than a few points of either are "
    f"usually double-counting.")


# --- Recovery framing --------------------------------------------------------
n_recent = (users.cohort_month >= "2024-11").sum() * SCALE
# Same cohort windows as Phase 2 (02_cohort_retention.csv), not typed-in values.
m1 = pd.read_csv(TAB / "02_cohort_retention.csv", index_col=0)["1"].dropna()
m1_early, m1_late = m1.loc["2024-01":"2024-09"].mean(), m1.loc["2024-11":"2025-05"].mean()
lost_users = (m1_early - m1_late) * n_recent
log(f"\n--- What 'recovery' means in user terms ---")
log(f"M+1 retention fell {(m1_early - m1_late) * 100:.1f} pp ({pct(m1_early)} -> "
    f"{pct(m1_late)}). Against the {n_recent:,.0f} users "
    f"acquired since 2024-11, that is ~{lost_users:,.0f} users who would have "
    f"returned under the old service level and did not.")
log(f"The recommended portfolio delivers "
    f"{passing.incremental_repeats_yr.sum():,} incremental repeat orders/yr. "
    f"This is a partial recovery by design: Phase 3 showed ~51% of the controlled "
    f"decline sits in systems the order log cannot observe (delivery speed, "
    f"stockouts, assortment). Closing the rest needs instrumentation we do not "
    f"currently have.")


# ===========================================================================
# SENSITIVITY -- computed, not asserted
# ===========================================================================
log("\n" + "-" * 78)
log("SENSITIVITY -- what breaks the case?")
log("-" * 78)

rows = []
for mult in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5]:
    for ltv in [1.0, LTV_MULT, LTV_MULT * 1.3]:
        net = 0.0
        for c in passing.itertuples():
            vpr = c.segment_aov * ltv * GROSS_MARGIN
            net += c.incremental_repeats_yr * mult * vpr + c.cost_avoided_yr - c.cost_yr
        rows.append({"uplift_multiplier": mult, "ltv_multiplier": round(ltv, 2),
                     "net": round(net, 0)})
sens = pd.DataFrame(rows).pivot(index="uplift_multiplier", columns="ltv_multiplier",
                                values="net")
log("\nNet annual contribution ($) of the recommended portfolio:")
log(sens.to_string())
sens.to_csv(TAB / "04_sensitivity.csv")

n_pos = int((sens > 0).sum().sum())
n_cells = sens.size
worst, best = sens.min().min(), sens.max().max()
log(f"\n  {n_pos}/{n_cells} scenarios are value-positive. "
    f"Range {usd(worst)} .. {usd(best)}.")

half = sens.loc[0.5]
if (half > 0).all():
    log("  At HALF the modelled uplift the portfolio stays positive under every "
        "LTV assumption tested -- the case does not depend on the effect sizes "
        "being right, because cost-to-serve savings carry a large share of it.")
else:
    bad = half[half <= 0]
    log(f"  At HALF the modelled uplift the portfolio goes negative when the LTV "
        f"multiplier is {list(bad.index)} -- i.e. the case DOES depend on "
        f"incremental repeats generating follow-on orders. Flagged, not hidden.")

zero_uplift_net = float(passing.cost_avoided_yr.sum() - passing.cost_yr.sum())
log(f"\n  Floor test -- if the repeat uplift were EXACTLY ZERO and only the "
    f"cost-to-serve savings landed, the portfolio nets {usd(zero_uplift_net)}. "
    f"{'That is the downside protection.' if zero_uplift_net > 0 else 'So some repeat uplift is required; there is no free floor.'}")


# ===========================================================================
# FIGURES
# ===========================================================================
SHORT = {
    "1. Tiered service recoveryA": "1A  Automated\nrecovery (2 tix)",
    "1. Tiered service recoveryB": "1B  Human callback\n(3+ tix)",
    "2. Electronics/Home post-purchase fixb": "2  Electronics/Home\npost-purchase fix",
    "3. Coupon-dependency weaningb": "3  Coupon-dependency\nweaning",
}
lbls = [SHORT[r.intervention + r.tier[0]] for r in base.itertuples()]

fig, axes = plt.subplots(1, 2, figsize=(17, 6))
ax = axes[0]
xx = np.arange(len(base))
ax.bar(xx - .22, base.revenue_contribution_yr / 1000, .22, label="Repeat contribution",
       color="#2e7d32")
ax.bar(xx, base.cost_avoided_yr / 1000, .22, label="Cost-to-serve avoided",
       color="#66bb6a")
ax.bar(xx + .22, base.cost_yr / 1000, .22, label="Programme cost", color="#c0392b")
ax.set_xticks(xx); ax.set_xticklabels(lbls, fontsize=8.5)
ax.set_ylabel("$000 / year"); ax.set_title("Base case: benefit vs cost")
ax.set_ylim(0, base.revenue_contribution_yr.max() / 1000 * 1.30)
ax.legend(frameon=False, fontsize=9.5, loc="upper left")

ax = axes[1]
for i, r in enumerate(base.itertuples()):
    col = "#1b3b6f" if r.clears_gate else "#c0392b"
    ax.barh(i, r.net_yr / 1000, color=col)
    ax.annotate(f"{r.roi:.2f}x", (r.net_yr / 1000, i), xytext=(6, 0),
                textcoords="offset points", va="center", fontsize=10, weight="bold")
ax.set_yticks(range(len(base))); ax.set_yticklabels(lbls, fontsize=8.5)
ax.axvline(0, color="black", lw=1.4)
ax.set_xlim(0, base.net_yr.max() / 1000 * 1.18)
ax.set_xlabel("Net annual contribution ($000)")
ax.set_title("Net value and ROI (red = fails break-even gate)")
fig.subplots_adjust(wspace=0.35)
fig.savefig(FIG / "04_business_case.png"); plt.close(fig)

fig, ax = plt.subplots(figsize=(9.5, 5.5))
sns.heatmap(sens / 1000, annot=True, fmt=".0f", cmap="RdYlGn", center=0,
            cbar_kws={"label": "net contribution ($000)"}, ax=ax)
ax.set_xlabel("LTV multiplier"); ax.set_ylabel("Uplift multiplier")
ax.set_title("Sensitivity of the recommended portfolio")
fig.savefig(FIG / "04_sensitivity.png"); plt.close(fig)

log.save()
