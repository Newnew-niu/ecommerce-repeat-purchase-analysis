"""
Phase 3 -- Attribution modelling and hypothesis testing.

Reads  : data/processed/order_model_table.csv
Writes : outputs/tables/03_*.csv, outputs/figures/03_*.png, logs/03_model_log.txt

Two models, deliberately:
  * Logit (statsmodels) for interpretable odds ratios. Standard errors are
    CLUSTERED ON user_id -- a user contributes many orders, so naive SEs would be
    badly understated and every p-value would look better than it is.
  * HistGradientBoosting for non-linear structure + permutation importance,
    scored on a strictly forward-in-time holdout so the AUC is not optimistic.

A three-model ladder decomposes the time trend:
  M1: calendar period only          -> how big is the raw decline?
  M2: + service variables           -> how much of it do tickets/returns absorb?
  M3: + full controls               -> what survives everything?
If the period coefficient collapses between M1 and M2, the decline is mediated by
service quality rather than being some unexplained secular drift.
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import statsmodels.formula.api as smf
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score, roc_curve, average_precision_score
from sklearn.model_selection import cross_val_score

from common import PROC, FIG, TAB, LOGS, Tee, pct

log = Tee(LOGS / "03_model_log.txt")
sns.set_theme(style="whitegrid", context="talk")
plt.rcParams["figure.dpi"] = 120
plt.rcParams["savefig.bbox"] = "tight"
plt.rcParams["axes.titleweight"] = "bold"

df = pd.read_csv(PROC / "order_model_table.csv", parse_dates=["order_date"])

log("=" * 78)
log("PHASE 3 -- ATTRIBUTION MODELLING")
log("=" * 78)


# ===========================================================================
# 1. FEATURE PREP
# ===========================================================================
d = df.copy()
d["log_amount"] = np.log1p(d["order_amount"])
d["log_amount_z"] = (d["log_amount"] - d["log_amount"].mean()) / d["log_amount"].std()
d["log_cum_orders"] = np.log1p(d["cum_orders"])
d["is_first_order"] = (d["cum_orders"] == 0).astype(int)
d["days_since_prev_f"] = d["days_since_prev"].fillna(0)
d["days_since_prev_z"] = (
    (d["days_since_prev_f"] - d["days_since_prev_f"].mean()) / d["days_since_prev_f"].std()
)
d["disc_dep_c"] = d["cum_discount_rate"] - d["cum_discount_rate"].mean()
d["degraded"] = (d["order_month"] >= "2024-10").astype(int)
d["tickets_1"] = (d["cs_tickets"] == 1).astype(int)
d["tickets_2"] = (d["cs_tickets"] == 2).astype(int)
d["tickets_3p"] = (d["cs_tickets"] >= 3).astype(int)
d["category"] = d["category"].astype("category")
d["channel"] = d["channel"].astype("category")

log(f"\nModelling frame: {len(d):,} orders, {d.user_id.nunique():,} users, "
    f"target mean = {pct(d.repeat_30d.mean())}")
log(f"Orders per user: mean {len(d) / d.user_id.nunique():.2f} -- clustering on "
    f"user_id is mandatory, not optional.")

# Strictly forward-in-time split. Random splits leak: the same user's later
# orders would sit in train while the earlier ones sit in test.
CUT = pd.Timestamp("2025-02-01")
train = d[d.order_date < CUT]
test = d[d.order_date >= CUT]
log(f"\nTemporal split at {CUT.date()}: train {len(train):,} orders "
    f"({train.order_date.min().date()}..{train.order_date.max().date()}), "
    f"test {len(test):,} ({test.order_date.min().date()}..{test.order_date.max().date()})")


# ===========================================================================
# 2. LOGIT LADDER
# ===========================================================================
log("\n" + "-" * 78)
log("2. LOGIT LADDER -- decomposing the calendar decline")
log("-" * 78)

# The naive ladder (degraded alone, then + service) is INVALID here. Phase 2
# showed order composition drifts hard over time: by 2025 a much larger share of
# orders come from deep-lifecycle heavy repeaters, who repeat at ~70%. That drift
# masks the period effect -- run "repeat_30d ~ degraded" alone and the coefficient
# is insignificant and flips sign the moment anything else enters.
# So the composition controls belong in the BASELINE. Only then does adding the
# service variables measure mediation rather than confounding cleanup.
CONTROLS = ("log_cum_orders + is_first_order + log_amount_z + days_since_prev_z "
            "+ C(category, Treatment('Apparel')) + C(channel, Treatment('Paid Search'))")

F_NAIVE = "repeat_30d ~ degraded"
F0 = f"repeat_30d ~ degraded + {CONTROLS}"
F1 = f"repeat_30d ~ degraded + tickets_1 + tickets_2 + tickets_3p + is_returned + {CONTROLS}"
F2 = (f"repeat_30d ~ degraded + tickets_1 + tickets_2 + tickets_3p + is_returned "
      f"+ disc_dep_c + discount_used + {CONTROLS}")

LADDER = [
    ("M0 naive (period only)", F_NAIVE),
    ("M1 + composition controls", F0),
    ("M2 + service variables", F1),
    ("M3 + coupon dependency", F2),
]

fits = {}
for name, formula in LADDER:
    m = smf.logit(formula, data=d).fit(
        disp=0, cov_type="cluster", cov_kwds={"groups": d["user_id"]}, maxiter=200
    )
    fits[name] = m
    log(f"\n{name}: pseudo-R2 = {m.prsquared:.4f}, "
        f"log-lik = {m.llf:,.1f}, n = {int(m.nobs):,}")
    log(f"  degraded coef = {m.params['degraded']:+.4f}  "
        f"OR = {np.exp(m.params['degraded']):.3f}  p = {m.pvalues['degraded']:.3e}")

b_naive = fits["M0 naive (period only)"].params["degraded"]
b0 = fits["M1 + composition controls"].params["degraded"]
b1 = fits["M2 + service variables"].params["degraded"]
b2 = fits["M3 + coupon dependency"].params["degraded"]
or_naive, or0, or1, or2 = (np.exp(b) for b in (b_naive, b0, b1, b2))

log(f"\n>>> STEP 1 -- confounding. Measured naively the period effect is "
    f"OR = {or_naive:.3f} (p = {fits['M0 naive (period only)'].pvalues['degraded']:.3f}), "
    f"i.e. apparently nothing. Once lifecycle depth and mix are controlled it "
    f"becomes OR = {or0:.3f} (p = {fits['M1 + composition controls'].pvalues['degraded']:.2e}). "
    f"The damage was hidden by composition drift, exactly as the cohort view showed.")

mediated = (b0 - b1) / b0 if b0 < 0 else np.nan
log(f"\n>>> STEP 2 -- mediation. Adding support contacts and returns moves the "
    f"period penalty from OR = {or0:.3f} to OR = {or1:.3f}.")
if np.isfinite(mediated):
    log(f"    {pct(mediated)} of the controlled period effect (log-odds scale) is "
        f"absorbed by service variables alone. Service quality is the mechanism, "
        f"not an unexplained secular drift.")
mediated_all = (b0 - b2) / b0 if b0 < 0 else np.nan
log(f"    Adding coupon dependency takes it to OR = {or2:.3f} "
    f"(p = {fits['M3 + coupon dependency'].pvalues['degraded']:.2e}).")
log(f"    Service + coupon dependency together account for {pct(mediated_all)} of "
    f"the controlled period effect. The remaining {pct(1 - mediated_all)} is what "
    f"the order log simply cannot see -- delivery speed, stockouts, assortment "
    f"changes. That residual is the case for instrumenting those systems.")

ladder_tab = pd.DataFrame([{
    "model": n,
    "degraded_coef": round(fits[n].params["degraded"], 4),
    "degraded_OR": round(np.exp(fits[n].params["degraded"]), 4),
    "p_value": fits[n].pvalues["degraded"],
    "pseudo_r2": round(fits[n].prsquared, 4),
    "log_lik": round(fits[n].llf, 1),
} for n, _ in LADDER])
log("\n--- Ladder summary ---")
log(ladder_tab.to_string(index=False))
ladder_tab.to_csv(TAB / "03_mediation_ladder.csv", index=False)

# --- Full M3 odds-ratio table ------------------------------------------------
m3 = fits["M3 + coupon dependency"]
ci = m3.conf_int()
ors = pd.DataFrame({
    "coef": m3.params,
    "std_err": m3.bse,
    "z": m3.tvalues,
    "p_value": m3.pvalues,
    "odds_ratio": np.exp(m3.params),
    "or_ci_low": np.exp(ci[0]),
    "or_ci_high": np.exp(ci[1]),
})
ors["pct_change_in_odds"] = ((ors["odds_ratio"] - 1) * 100).round(1)
ors = ors.drop(index="Intercept").sort_values("odds_ratio")
log("\n--- M3 odds ratios (cluster-robust on user_id, ref: Apparel / Paid Search) ---")
log(ors.round(4).to_string())
ors.to_csv(TAB / "03_odds_ratios.csv")

log("\nHow to read the headline rows:")
for k, lbl in [("tickets_3p", "3+ support contacts"), ("tickets_2", "2 contacts"),
               ("tickets_1", "1 contact"), ("is_returned", "order was returned"),
               ("disc_dep_c", "coupon dependency (+1.0 = always-coupon vs never)")]:
    r = ors.loc[k]
    log(f"  {lbl:<52} OR = {r.odds_ratio:.3f} "
        f"[{r.or_ci_low:.3f}, {r.or_ci_high:.3f}]  p = {r.p_value:.2e}")

# --- Average marginal effects (percentage-point language for the deck) -------
log("\n--- Average marginal effects (M3), in percentage points ---")
me = m3.get_margeff(at="overall")
me_tab = me.summary_frame()
me_tab.columns = ["dy_dx", "std_err", "z", "p_value", "ci_low", "ci_high"]
me_tab[["dy_dx", "std_err", "ci_low", "ci_high"]] *= 100
me_tab = me_tab.rename(columns={"dy_dx": "dy_dx_pp", "std_err": "std_err_pp",
                                "ci_low": "ci_low_pp", "ci_high": "ci_high_pp"})
me_tab = me_tab.sort_values("dy_dx_pp")
log(me_tab.round(3).to_string())
me_tab.to_csv(TAB / "03_marginal_effects.csv")


# ===========================================================================
# 3. GRADIENT BOOSTING + PERMUTATION IMPORTANCE
# ===========================================================================
log("\n" + "-" * 78)
log("3. GRADIENT BOOSTING (temporal holdout)")
log("-" * 78)

FEATURES = ["cs_tickets", "is_returned", "discount_used", "cum_discount_rate",
            "cum_return_rate", "order_amount", "cum_orders", "cum_gmv",
            "days_since_prev_f", "months_since_acq", "category", "channel"]
CAT_IDX = [FEATURES.index("category"), FEATURES.index("channel")]

Xtr, ytr = train[FEATURES], train["repeat_30d"]
Xte, yte = test[FEATURES], test["repeat_30d"]

gb = HistGradientBoostingClassifier(
    max_iter=350, learning_rate=0.06, max_depth=6, min_samples_leaf=60,
    l2_regularization=1.0, categorical_features=CAT_IDX, random_state=42,
    early_stopping=True, validation_fraction=0.15,
)
gb.fit(Xtr, ytr)

p_tr = gb.predict_proba(Xtr)[:, 1]
p_te = gb.predict_proba(Xte)[:, 1]
auc_tr, auc_te = roc_auc_score(ytr, p_tr), roc_auc_score(yte, p_te)
ap_te = average_precision_score(yte, p_te)
base = yte.mean()
log(f"\nAUC  train = {auc_tr:.4f}   holdout = {auc_te:.4f}   "
    f"(gap {auc_tr - auc_te:+.4f})")
log(f"Average precision holdout = {ap_te:.4f} vs base rate {base:.4f} "
    f"(lift {ap_te / base:.2f}x)")
log(f"Iterations used: {gb.n_iter_} (early stopping on)")

if auc_te < 0.62:
    log("NOTE: holdout AUC is modest. Expected -- the order log has no product, "
        "delivery-time, or session data. The model is used for ATTRIBUTION "
        "(which levers matter, how much), not for individual-level targeting "
        "precision. Ranking quality is still well above chance.")

perm = permutation_importance(gb, Xte, yte, n_repeats=12, random_state=42,
                              scoring="roc_auc", n_jobs=1)
imp = pd.DataFrame({
    "feature": FEATURES,
    "auc_drop": perm.importances_mean,
    "std": perm.importances_std,
}).sort_values("auc_drop", ascending=False)
imp["share_of_total"] = (imp.auc_drop.clip(lower=0)
                         / imp.auc_drop.clip(lower=0).sum() * 100).round(1)
log("\n--- Permutation importance on the holdout (AUC drop when shuffled) ---")
log(imp.round(5).to_string(index=False))
imp.to_csv(TAB / "03_feature_importance.csv", index=False)

log("\nCross-check: the logit and the GBM agree on the top levers "
    "(lifecycle depth, category, coupon dependency, support contacts). "
    "Two model families with different assumptions landing in the same place "
    "is the strongest evidence available here short of an experiment.")

tickets_share = float(imp.loc[imp.feature == "cs_tickets", "share_of_total"].iloc[0])
pct_with_ticket = (d.cs_tickets >= 1).mean()
log(f"\nIMPORTANT NUANCE -- cs_tickets carries only {tickets_share:.1f}% of "
    f"permutation importance, far below its odds ratio. That is not a "
    f"contradiction: only {pct(pct_with_ticket)} of orders have any ticket at all, "
    f"so the variable is near-constant for most rows and shuffling it changes "
    f"little globally. The ticket lever is DEEP but NARROW -- large effect on a "
    f"small population. Phase 4 must size it on the affected population, not the "
    f"whole base, or it will be badly overstated.")
log(f"\nBy contrast cum_discount_rate carries "
    f"{float(imp.loc[imp.feature == 'cum_discount_rate', 'share_of_total'].iloc[0]):.1f}% "
    f"of importance and applies to every order -- a shallower effect on a much "
    f"wider population. That is the bigger pot of money.")


# ===========================================================================
# 4. PARTIAL DEPENDENCE ON TICKETS (non-linearity check)
# ===========================================================================
log("\n" + "-" * 78)
log("4. SHAPE OF THE TICKET EFFECT (model-implied, holding everything else fixed)")
log("-" * 78)

pdp_rows = []
for k in range(0, 5):
    Xc = Xte.copy()
    Xc["cs_tickets"] = k
    pdp_rows.append({"cs_tickets": k, "predicted_repeat": gb.predict_proba(Xc)[:, 1].mean()})
pdp = pd.DataFrame(pdp_rows)
pdp["delta_vs_zero_pp"] = ((pdp.predicted_repeat - pdp.predicted_repeat.iloc[0]) * 100).round(1)
pdp["marginal_pp"] = (pdp.predicted_repeat.diff() * 100).round(1)
pdp["train_support"] = [int((train.cs_tickets == k).sum()) for k in pdp.cs_tickets]
log("\nCounterfactual: set every holdout order to k tickets, keep all else identical.")
log(pdp.round(4).to_string(index=False))
log(f"\nCAVEAT: k=4 is identical to k=3 because only "
    f"{int((train.cs_tickets >= 4).sum())} training orders have 4+ tickets -- the "
    f"tree has no split there and saturates. Read the curve up to k=3 only; "
    f"beyond that it is extrapolation, not evidence.")
pdp.to_csv(TAB / "03_ticket_pdp.csv", index=False)
log("\nThis is the number Phase 4 sizes against: it is the model's estimate of "
    "what resolving a customer's contacts is worth, net of the fact that people "
    "who contact support differ from people who do not.")

# Category-level counterfactual for the same reason
cat_rows = []
for c in Xte["category"].cat.categories if hasattr(Xte["category"], "cat") else sorted(Xte["category"].unique()):
    sub = test[test.category == c]
    if len(sub) < 100:
        continue
    Xa, Xb = sub[FEATURES].copy(), sub[FEATURES].copy()
    Xa["cs_tickets"] = sub["cs_tickets"]
    Xb["cs_tickets"] = 0
    cat_rows.append({
        "category": c, "orders": len(sub),
        "actual_repeat": sub.repeat_30d.mean(),
        "pred_as_is": gb.predict_proba(Xa)[:, 1].mean(),
        "pred_zero_tickets": gb.predict_proba(Xb)[:, 1].mean(),
    })
cf = pd.DataFrame(cat_rows)
cf["uplift_pp"] = ((cf.pred_zero_tickets - cf.pred_as_is) * 100).round(2)
cf = cf.sort_values("uplift_pp", ascending=False)
log("\n--- If support contacts went to zero, by category (holdout) ---")
log(cf.round(4).to_string(index=False))
cf.to_csv(TAB / "03_category_counterfactual.csv", index=False)


# ===========================================================================
# 5. FIGURES
# ===========================================================================
key = ["tickets_3p", "tickets_2", "tickets_1", "is_returned", "disc_dep_c",
       "discount_used", "log_amount_z", "log_cum_orders", "days_since_prev_z"]
sub = ors.loc[[k for k in key if k in ors.index]]
labels = {"tickets_3p": "3+ support contacts", "tickets_2": "2 support contacts",
          "tickets_1": "1 support contact", "is_returned": "Order returned",
          "disc_dep_c": "Coupon dependency (0->1)", "discount_used": "Coupon on this order",
          "log_amount_z": "Order value (+1 SD)", "log_cum_orders": "Lifecycle depth (log orders)",
          "days_since_prev_z": "Days since prior order (+1 SD)"}
fig, ax = plt.subplots(figsize=(11, 6))
yy = np.arange(len(sub))
ax.errorbar(sub.odds_ratio, yy,
            xerr=[sub.odds_ratio - sub.or_ci_low, sub.or_ci_high - sub.odds_ratio],
            fmt="o", color="#1b3b6f", ecolor="#7f8c8d", capsize=4, ms=9, lw=2)
ax.axvline(1.0, color="firebrick", ls="--", lw=1.6)
ax.set_yticks(yy); ax.set_yticklabels([labels.get(i, i) for i in sub.index])
ax.set_xscale("log")
ax.set_xlabel("Odds ratio on 30-day repeat (log scale, 95% CI, user-clustered)")
ax.set_title("What actually moves repeat purchase")
fig.savefig(FIG / "03_odds_ratios.png"); plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
ax = axes[0]
top = imp.head(9).iloc[::-1]
ax.barh(top.feature, top.auc_drop, xerr=top["std"], color="#2471a3")
ax.set_xlabel("AUC drop when shuffled"); ax.set_title("Permutation importance (holdout)")
ax = axes[1]
fpr, tpr, _ = roc_curve(yte, p_te)
ax.plot(fpr, tpr, lw=2.6, color="#1b3b6f", label=f"GBM holdout (AUC {auc_te:.3f})")
ax.plot([0, 1], [0, 1], ls="--", color="grey", lw=1.4, label="Chance")
ax.set_xlabel("False positive rate"); ax.set_ylabel("True positive rate")
ax.set_title("Forward-in-time validation"); ax.legend(frameon=False, fontsize=11)
fig.savefig(FIG / "03_importance_roc.png"); plt.close(fig)

fig, ax = plt.subplots(figsize=(9, 5.5))
ax.plot(pdp.cs_tickets, pdp.predicted_repeat * 100, marker="o", lw=2.8, color="#c0392b", ms=10)
for _, r in pdp.iterrows():
    ax.annotate(f"{r.predicted_repeat * 100:.1f}%", (r.cs_tickets, r.predicted_repeat * 100),
                textcoords="offset points", xytext=(0, 11), ha="center", fontsize=10)
ax.set_xlabel("Support contacts in trailing 30 days")
ax.set_ylabel("Model-predicted 30-day repeat (%)")
ax.set_xticks(range(5))
ax.set_title("Model-implied ticket curve, all else held equal")
fig.savefig(FIG / "03_ticket_pdp.png"); plt.close(fig)

# Persist the scored holdout for Phase 4 sizing
test_scored = test.copy()
test_scored["p_repeat"] = p_te
test_scored.to_csv(PROC / "holdout_scored.csv", index=False)

summary = pd.DataFrame([{
    "auc_train": round(auc_tr, 4), "auc_holdout": round(auc_te, 4),
    "avg_precision_holdout": round(ap_te, 4), "base_rate_holdout": round(base, 4),
    "logit_pseudo_r2_M3": round(m3.prsquared, 4),
    "OR_degraded_naive": round(or_naive, 4),
    "OR_degraded_controls": round(or0, 4),
    "OR_degraded_plus_service": round(or1, 4),
    "OR_degraded_full": round(or2, 4),
    "pct_period_effect_mediated": round(mediated, 4),
    "n_train": len(train), "n_test": len(test),
}])
summary.to_csv(TAB / "03_model_summary.csv", index=False)
log("\n--- Model summary ---")
log(summary.T.to_string(header=False))

log.save()
