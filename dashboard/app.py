"""
Repeat Purchase Dashboard (Streamlit).

Run from the repository root:
    streamlit run dashboard/app.py

Interactive views are computed live from data/processed/orders_clean.csv with the
same functions the analysis uses (src/kpis.py), so every KPI here matches the
report. Model and business-case views read the validated tables in
outputs/tables/ (they come from the full-sample models and are not re-fit when
filters change).

The data is SIMULATED -- see the "Data & definitions" tab.
"""

import subprocess
import sys
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from common import PROC, TAB, SNAPSHOT, REPEAT_WINDOW, CATEGORY_ORDER  # noqa: E402
import kpis  # noqa: E402

st.set_page_config(page_title="Repeat Purchase Dashboard", page_icon="📈", layout="wide")

# Palette (validated categorical slots + chart ink; see dataviz reference palette)
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#898781"
SERIES = {"Headline (all orders)": GREY, "New customers": BLUE,
          "Established (3+ prior orders)": ORANGE}
MIN_CELL = 30


# ===========================================================================
# DATA
# ===========================================================================
def build_data():
    """Generate and clean the dataset (Phases 0-1). ~30 seconds."""
    for script in ("00_make_dataset.py", "01_clean_features.py"):
        subprocess.run([sys.executable, script], cwd=ROOT / "src", check=True,
                       capture_output=True)


@st.cache_data(show_spinner="Loading orders...")
def load():
    orders = kpis.load_orders()
    orders["order_month"] = orders["order_month"].astype(str)
    firsts = kpis.first_orders(orders)
    meta = firsts.set_index("user_id")[["cohort_month", "channel", "category"]]
    meta.columns = ["cohort_month", "channel", "first_category"]
    users = pd.read_csv(PROC / "user_features.csv")
    return orders, meta, users


@st.cache_data
def table(name, **kw):
    return pd.read_csv(TAB / name, **kw)


if not (PROC / "orders_clean.csv").exists():
    st.title("Repeat Purchase Dashboard")
    st.warning("Processed data not found. The dataset is generated locally "
               "(it is not stored in git). Build it now, or run "
               "`python src/run_all.py` from the repository root.")
    if st.button("Build dataset (about 30 seconds)"):
        with st.spinner("Generating and cleaning data..."):
            build_data()
        st.rerun()
    st.stop()

orders, cust_meta, users = load()
MONTHS = sorted(orders["order_month"].unique())


# ===========================================================================
# SIDEBAR FILTERS
# ===========================================================================
st.sidebar.header("Filters")
m_from, m_to = st.sidebar.select_slider("Month range", options=MONTHS,
                                        value=(MONTHS[0], MONTHS[-1]))
channels = sorted(orders["channel"].unique())
sel_ch = st.sidebar.multiselect("Acquisition channel", channels, default=channels)
cats = [c for c in CATEGORY_ORDER if c in orders["category"].unique()] + ["Unknown"]
sel_cat = st.sidebar.multiselect("Category", cats, default=cats)
st.sidebar.caption(
    "**How filters apply.** Order-level metrics (GMV, AOV, headline repeat) use the "
    "*order* month and *order* category. Customer-level metrics (new-customer "
    "repeat, cohorts, time to 2nd order) use the customer's *acquisition* month and "
    "*first-order* category, and include all of those customers' later orders.")
st.sidebar.divider()
st.sidebar.caption(f"Snapshot date: {SNAPSHOT.date()}. Orders within {REPEAT_WINDOW} "
                   f"days of the snapshot are excluded from repeat rates (censoring).")

if not sel_ch or not sel_cat:
    st.warning("Select at least one channel and one category.")
    st.stop()


@st.cache_data
def filtered(m_from, m_to, sel_ch, sel_cat):
    o = orders[orders.order_month.between(m_from, m_to)
               & orders.channel.isin(sel_ch) & orders.category.isin(sel_cat)]
    cm = cust_meta[cust_meta.cohort_month.between(m_from, m_to)
                   & cust_meta.channel.isin(sel_ch)
                   & cust_meta.first_category.isin(sel_cat)]
    c = orders[orders.user_id.isin(cm.index)]
    return o, c


o_f, c_f = filtered(m_from, m_to, tuple(sel_ch), tuple(sel_cat))
if o_f.empty or c_f.empty:
    st.warning("No data for this selection.")
    st.stop()


def fmt_pct(x, d=1):
    return "–" if pd.isna(x) else f"{100 * x:.{d}f}%"


def baseline_recent_note():
    return ("Baseline = 2024Q2–Q3, recent = 2025Q1–Q2 (the comparison used in the "
            "report).")


# ===========================================================================
# HEADER + KPI TILES
# ===========================================================================
st.title("E-commerce Repeat Purchase Dashboard")
st.caption("Why is repeat purchasing declining, and what should we do about it? "
           "· Simulated order log, 2024-01 to 2025-06 · "
           "[Full report on GitHub](https://github.com/Newnew-niu/ecommerce-repeat-purchase-analysis/blob/main/REPORT.md)")
st.info("**Data note:** this dashboard runs on a *simulated* order log built for a "
        "portfolio project. Methods transfer to real data; absolute numbers do not.",
        icon="ℹ️")

snap_o = kpis.kpi_snapshot(o_f)
snap_c = kpis.kpi_snapshot(c_f)

r1 = st.columns(4)
r1[0].metric("GMV", f"${snap_o['gmv']:,.0f}")
r1[1].metric("Orders", f"{snap_o['orders']:,}")
r1[2].metric("Active customers", f"{snap_o['customers']:,}")
r1[3].metric("Average order value", f"${snap_o['aov']:,.2f}")
r2 = st.columns(4)
r2[0].metric("Order-level 30-day repeat (headline)", fmt_pct(snap_o["order_repeat_30d"]),
             help="Share of orders followed by another order from the same customer "
                  "within 30 days. Unit: order.")
r2[1].metric("New-customer 30-day repeat", fmt_pct(snap_c["new_customer_repeat_30d"]),
             help="Share of first-time customers who order again within 30 days of "
                  "their first order. Unit: customer.")
r2[2].metric("90-day repeat customer rate", fmt_pct(snap_c["repeat_customer_90d"]),
             help="Share of new customers with a 2nd order within 90 days, among those "
                  "acquired at least 90 days before the snapshot.")
r2[3].metric("Median days to 2nd order", f"{snap_c['median_days_to_2nd']:.0f}",
             help="Among customers who placed a second order.")

tab_over, tab_ret, tab_cust, tab_drv, tab_rec, tab_def = st.tabs([
    "Overview", "Retention & cohorts", "Customer behavior", "Drivers",
    "Recommendations", "Data & definitions"])


# ===========================================================================
# OVERVIEW
# ===========================================================================
with tab_over:
    st.subheader("The headline repeat rate hides the decline")
    obs_o = o_f[o_f.observable == 1]
    obs_c = c_f[(c_f.order_seq == 0) & (c_f.observable == 1)]
    head = obs_o.groupby("order_month")["repeat_30d"].agg(["mean", "size"])
    newc = obs_c.groupby("cohort_month")["repeat_30d"].agg(["mean", "size"])
    est = obs_o[obs_o.cum_orders >= 3].groupby("order_month")["repeat_30d"].agg(["mean", "size"])
    trend = pd.concat([
        head.assign(series="Headline (all orders)"),
        newc.assign(series="New customers"),
        est.assign(series="Established (3+ prior orders)"),
    ]).reset_index(names="month")
    trend = trend[trend["size"] >= MIN_CELL]

    line = alt.Chart(trend).mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2).encode(
        x=alt.X("month:O", title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("mean:Q", title="30-day repeat rate", axis=alt.Axis(format="%"),
                scale=alt.Scale(zero=False)),
        color=alt.Color("series:N", title=None,
                        scale=alt.Scale(domain=list(SERIES), range=list(SERIES.values())),
                        legend=alt.Legend(orient="top", labelLimit=0)),
        tooltip=[alt.Tooltip("series:N", title="Series"), alt.Tooltip("month:O", title="Month"),
                 alt.Tooltip("mean:Q", title="Repeat rate", format=".1%"),
                 alt.Tooltip("size:Q", title="Base (n)", format=",")],
    )
    rule = alt.Chart(pd.DataFrame({"month": ["2024-10"]})).mark_rule(
        strokeDash=[4, 4], color=GREY).encode(x="month:O")
    st.altair_chart((line + rule).properties(height=360), width="stretch")
    st.caption("Headline: order month. New customers: acquisition month. Established: "
               "orders from customers with 3+ prior orders. Points with fewer than "
               f"{MIN_CELL} observations are hidden. Dashed line: 2024-10, when support "
               "ticket load began rising.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**What this shows**")
        st.markdown(
            "- The headline rate moves only ~2pp because a growing share of orders "
            "comes from loyal, high-frequency customers.\n"
            "- Measured per *new customer*, repeat fell from **46.2% to 38.7%** "
            "(baseline vs recent, p = 2.6e-11), and cohort M+1 retention from "
            "**34.7% to 27.2%**.\n"
            "- Decisions should track new-customer repeat and cohort retention, "
            "not the headline rate.")
        st.caption("Bold figures: full-sample results from the report. "
                   + baseline_recent_note())
    with c2:
        st.markdown("**Share of orders from loyal customers (4+ prior orders)**")
        mix = o_f.groupby("order_month").apply(
            lambda d: (d.cum_orders >= 4).mean(), include_groups=False).rename("share")
        mix = mix.reset_index()
        st.altair_chart(alt.Chart(mix).mark_bar(color=BLUE, cornerRadiusTopLeft=3,
                                                cornerRadiusTopRight=3).encode(
            x=alt.X("order_month:O", title=None, axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("share:Q", title="Share of orders", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("order_month:O", title="Month"),
                     alt.Tooltip("share:Q", title="Share", format=".1%")],
        ).properties(height=240), width="stretch")


# ===========================================================================
# RETENTION & COHORTS
# ===========================================================================
with tab_ret:
    st.subheader("Cohort retention: every cohort since 2024-11 retains worse")
    ret = kpis.cohort_retention(c_f)
    sizes = ret.pop("cohort_size")
    long = ret.iloc[:, :13].stack().rename("retention").reset_index()
    long.columns = ["cohort", "month_n", "retention"]
    long = long[long.month_n >= 1]
    long["cohort_size"] = long.cohort.map(sizes)
    heat = alt.Chart(long).mark_rect(stroke="white", strokeWidth=1).encode(
        x=alt.X("month_n:O", title="Months since acquisition (M+n)", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("cohort:O", title="Acquisition cohort"),
        color=alt.Color("retention:Q", title="Active",
                        scale=alt.Scale(scheme="blues", domain=[0, 0.4], clamp=True),
                        legend=alt.Legend(format="%")),
        tooltip=[alt.Tooltip("cohort:O", title="Cohort"),
                 alt.Tooltip("month_n:O", title="M+n"),
                 alt.Tooltip("retention:Q", title="Retention", format=".1%"),
                 alt.Tooltip("cohort_size:Q", title="Cohort size", format=",")],
    )
    text = alt.Chart(long).mark_text(fontSize=10).encode(
        x="month_n:O", y="cohort:O", text=alt.Text("retention:Q", format=".0%"),
        color=alt.condition("datum.retention > 0.22", alt.value("white"),
                            alt.value("#0b0b0b")))
    st.altair_chart((heat + text).properties(height=520), width="stretch")
    st.caption("Cell = share of the cohort placing at least one order in calendar month "
               "M+n. M+0 (100% by definition) is omitted. Months not yet reached by the "
               "snapshot are blank.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**M+1 retention by cohort**")
        m1 = pd.DataFrame({"cohort": ret.index, "m1": ret[1].values,
                           "size": sizes.values}).dropna()
        m1["period"] = np.where(m1.cohort >= "2024-11", "2024-11 onward", "Before 2024-11")
        st.altair_chart(alt.Chart(m1).mark_bar(cornerRadiusTopLeft=3,
                                               cornerRadiusTopRight=3).encode(
            x=alt.X("cohort:O", title=None, axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("m1:Q", title="M+1 retention", axis=alt.Axis(format="%")),
            color=alt.Color("period:N", title=None,
                            scale=alt.Scale(domain=["Before 2024-11", "2024-11 onward"],
                                            range=[BLUE, ORANGE]),
                            legend=alt.Legend(orient="top", labelLimit=0)),
            tooltip=[alt.Tooltip("cohort:O"), alt.Tooltip("m1:Q", title="M+1", format=".1%"),
                     alt.Tooltip("size:Q", title="Cohort size", format=",")],
        ).properties(height=280), width="stretch")
    with c2:
        st.markdown("**Robustness: the decline holds at 30, 60 and 90 days**")
        sens = table("05_window_sensitivity.csv")
        sl = pd.concat([
            sens[["window_days", "baseline_rate", "baseline_n"]].set_axis(
                ["window", "rate", "n"], axis=1).assign(group="Baseline cohorts (2024-04..09)"),
            sens[["window_days", "recent_rate", "recent_n"]].set_axis(
                ["window", "rate", "n"], axis=1).assign(group="Recent cohorts (2024-11..2025-03)"),
        ])
        sl["window"] = sl.window.astype(str) + "-day"
        st.altair_chart(alt.Chart(sl).mark_bar(cornerRadiusTopLeft=3,
                                               cornerRadiusTopRight=3).encode(
            x=alt.X("window:N", title=None, sort=["30-day", "60-day", "90-day"],
                    axis=alt.Axis(labelAngle=0)),
            xOffset="group:N",
            y=alt.Y("rate:Q", title="New customers who reorder", axis=alt.Axis(format="%")),
            color=alt.Color("group:N", title=None, scale=alt.Scale(range=[BLUE, ORANGE]),
                            legend=alt.Legend(orient="top", labelLimit=0)),
            tooltip=[alt.Tooltip("group:N"), alt.Tooltip("window:N"),
                     alt.Tooltip("rate:Q", format=".1%"), alt.Tooltip("n:Q", format=",")],
        ).properties(height=280), width="stretch")
        st.caption("Full sample, fixed population (not affected by filters). All three "
                   "differences: p < 1e-10.")


# ===========================================================================
# CUSTOMER BEHAVIOR
# ===========================================================================
with tab_cust:
    st.subheader("First-time vs repeat customers")
    users_f = users[users.user_id.isin(c_f.user_id.unique())].copy()
    users_f["customer_type"] = np.where(users_f.frequency >= 2, "Repeat (2+ orders)",
                                        "One-time")
    ct = users_f.groupby("customer_type").agg(customers=("user_id", "size"),
                                              gmv=("monetary", "sum"),
                                              aov=("aov", "mean"),
                                              lifetime_gmv=("monetary", "mean"))
    ct["Customer share"] = ct.customers / ct.customers.sum()
    ct["GMV share"] = ct.gmv / ct.gmv.sum()

    c1, c2 = st.columns([1.1, 1])
    with c1:
        share = ct[["Customer share", "GMV share"]].reset_index().melt(
            "customer_type", var_name="measure", value_name="share")
        st.altair_chart(alt.Chart(share).mark_bar().encode(
            y=alt.Y("measure:N", title=None),
            x=alt.X("share:Q", stack="normalize", title=None, axis=alt.Axis(format="%")),
            color=alt.Color("customer_type:N", title=None,
                            scale=alt.Scale(domain=["Repeat (2+ orders)", "One-time"],
                                            range=[BLUE, "#9ec5f4"]),
                            legend=alt.Legend(orient="top", labelLimit=0)),
            tooltip=[alt.Tooltip("customer_type:N", title="Type"),
                     alt.Tooltip("measure:N"), alt.Tooltip("share:Q", format=".1%")],
        ).properties(height=alt.Step(44)), width="stretch")
        show = ct[["customers", "aov", "lifetime_gmv"]].rename_axis("Customer type").rename(columns={
            "customers": "Customers", "aov": "Avg order value", "lifetime_gmv": "Avg lifetime GMV"})
        st.dataframe(show.style.format({"Customers": "{:,}", "Avg order value": "${:,.2f}",
                                        "Avg lifetime GMV": "${:,.2f}"}), width="stretch")
    with c2:
        st.markdown("**What this shows**")
        st.markdown(
            "- Repeat customers generate most GMV through **frequency**, not basket "
            "size; their average order value is *lower* than one-time buyers'.\n"
            "- Retaining a new customer past the first order is therefore the main "
            "value lever.")
        st.caption("'Repeat customer' = 2+ orders ever. This is tenure-biased (recent "
                   "customers had less time), so it is used for GMV attribution, not trends.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Purchase frequency: orders per customer**")
        bins = pd.cut(users_f.frequency, [0, 1, 2, 3, 5, 9, 1000],
                      labels=["1", "2", "3", "4–5", "6–9", "10+"])
        fd = bins.value_counts(normalize=True).sort_index().rename("share").reset_index()
        fd.columns = ["orders", "share"]
        st.altair_chart(alt.Chart(fd).mark_bar(color=BLUE, cornerRadiusTopLeft=3,
                                               cornerRadiusTopRight=3).encode(
            x=alt.X("orders:O", title="Lifetime orders", sort=list(fd.orders),
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("share:Q", title="Share of customers", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("orders:O"), alt.Tooltip("share:Q", format=".1%")],
        ).properties(height=260), width="stretch")
    with c2:
        st.markdown("**Time from first to second order**")
        tts = kpis.time_to_second_order(c_f)
        tts = tts[tts <= 180]
        td = pd.cut(tts, range(0, 181, 15), include_lowest=True).value_counts().sort_index()
        td = pd.DataFrame({"from": range(0, 180, 15), "customers": td.values})
        td["in_window"] = np.where(td["from"] < 30, "Within 30 days", "After 30 days")
        st.altair_chart(alt.Chart(td).mark_bar(cornerRadiusTopLeft=3,
                                               cornerRadiusTopRight=3).encode(
            x=alt.X("from:O", title="Days to 2nd order (15-day bins, start)",
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("customers:Q", title="Customers"),
            color=alt.Color("in_window:N", title=None,
                            scale=alt.Scale(domain=["Within 30 days", "After 30 days"],
                                            range=[BLUE, "#9ec5f4"]),
                            legend=alt.Legend(orient="top", labelLimit=0)),
            tooltip=[alt.Tooltip("from:O", title="From day"),
                     alt.Tooltip("customers:Q", format=",")],
        ).properties(height=260), width="stretch")
        st.caption("Second orders within 180 days only. On this simulated data the drop "
                   "after day 30 is partly built into the generator.")

    st.markdown("**RFM segments**")
    rfm = users_f.groupby("rfm_segment").agg(
        customers=("user_id", "size"), gmv=("monetary", "sum"),
        avg_orders=("frequency", "mean"), avg_recency=("recency_days", "mean"))
    rfm["gmv_share"] = rfm.gmv / rfm.gmv.sum()
    rfm = rfm.sort_values("gmv", ascending=False).reset_index()
    st.altair_chart(alt.Chart(rfm).mark_bar(color=BLUE, cornerRadiusTopRight=3,
                                            cornerRadiusBottomRight=3).encode(
        y=alt.Y("rfm_segment:N", title=None, sort="-x"),
        x=alt.X("gmv_share:Q", title="Share of GMV", axis=alt.Axis(format="%")),
        tooltip=[alt.Tooltip("rfm_segment:N", title="Segment"),
                 alt.Tooltip("customers:Q", format=","),
                 alt.Tooltip("gmv_share:Q", title="GMV share", format=".1%"),
                 alt.Tooltip("avg_orders:Q", title="Avg orders", format=".2f"),
                 alt.Tooltip("avg_recency:Q", title="Avg days since last order", format=".0f")],
    ).properties(height=240), width="stretch")
    st.caption("RFM quintiles are computed on the full customer base at the snapshot. "
               "'At Risk (high value)': frequent past buyers who have not ordered in ~1 year "
               "-- a win-back target.")


# ===========================================================================
# DRIVERS
# ===========================================================================
with tab_drv:
    st.subheader("What is associated with lower repeat purchase")
    obs = o_f[o_f.observable == 1]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Repeat rate by support tickets on the order**")
        tk = obs.assign(t=np.minimum(obs.cs_tickets, 3).astype(int).astype(str)
                        .replace({"3": "3+"})).groupby("t")["repeat_30d"].agg(["mean", "size"])
        tk = tk[tk["size"] >= MIN_CELL].reset_index()
        st.altair_chart(alt.Chart(tk).mark_bar(cornerRadiusTopLeft=3,
                                               cornerRadiusTopRight=3).encode(
            x=alt.X("t:O", title="Support tickets", sort=["0", "1", "2", "3+"],
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("mean:Q", title="30-day repeat rate", axis=alt.Axis(format="%")),
            color=alt.condition("datum.t == '3+'", alt.value(ORANGE), alt.value(BLUE)),
            tooltip=[alt.Tooltip("t:O", title="Tickets"),
                     alt.Tooltip("mean:Q", title="Repeat", format=".1%"),
                     alt.Tooltip("size:Q", title="Orders", format=",")],
        ).properties(height=260), width="stretch")
    with c2:
        st.markdown("**Repeat rate by coupon history (customers with 3+ prior orders)**")
        deep = obs[obs.cum_orders >= 3]
        bands = pd.cut(deep.cum_discount_rate, [-.01, .2, .4, .6, .8, 1.0],
                       labels=["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"])
        cd = deep.groupby(bands, observed=True)["repeat_30d"].agg(["mean", "size"])
        cd = cd[cd["size"] >= MIN_CELL].reset_index(names="band")
        cd["band"] = cd["band"].astype(str)
        st.altair_chart(alt.Chart(cd).mark_bar(color=BLUE, cornerRadiusTopLeft=3,
                                               cornerRadiusTopRight=3).encode(
            x=alt.X("band:O", title="Share of prior orders using a coupon",
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("mean:Q", title="30-day repeat rate", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("band:O"), alt.Tooltip("mean:Q", format=".1%"),
                     alt.Tooltip("size:Q", title="Orders", format=",")],
        ).properties(height=260), width="stretch")
    st.caption("Restricting coupon history to customers with 3+ prior orders avoids a "
               "trap: a one-order customer who used a coupon has a 100% coupon rate by "
               f"construction. Cells with fewer than {MIN_CELL} orders are hidden.")

    st.markdown("**Category comparison**")
    cat = obs.groupby("category").agg(orders=("repeat_30d", "size"),
                                      repeat=("repeat_30d", "mean"),
                                      aov=("order_amount", "mean"),
                                      tickets=("cs_tickets", "mean"),
                                      returns=("is_returned", "mean"))
    cat = cat[cat.orders >= MIN_CELL].sort_values("repeat", ascending=False)
    st.dataframe(cat.rename_axis("Category").rename(columns={"orders": "Orders", "repeat": "30-day repeat",
                                     "aov": "AOV", "tickets": "Avg tickets",
                                     "returns": "Return rate"})
                 .style.format({"Orders": "{:,}", "30-day repeat": "{:.1%}", "AOV": "${:,.2f}",
                                "Avg tickets": "{:.3f}", "Return rate": "{:.1%}"}),
                 width="stretch")

    st.markdown("**Model: odds ratios on 30-day repeat (full sample, controls for "
                "lifecycle, category, channel, order value)**")
    orr = table("03_odds_ratios.csv", index_col=0)
    labels = {"tickets_3p": "3+ support tickets", "tickets_2": "2 support tickets",
              "tickets_1": "1 support ticket", "disc_dep_c": "Coupon dependency (0→1)",
              "is_returned": "Order returned", "degraded": "Period from 2024-10",
              "discount_used": "Coupon on this order",
              "C(category, Treatment('Apparel'))[T.Electronics]": "Electronics (vs Apparel)",
              "C(category, Treatment('Apparel'))[T.Home]": "Home (vs Apparel)",
              "C(category, Treatment('Apparel'))[T.Grocery]": "Grocery (vs Apparel)",
              "C(channel, Treatment('Paid Search'))[T.Organic]": "Organic (vs Paid Search)",
              "C(channel, Treatment('Paid Search'))[T.Affiliate]": "Affiliate (vs Paid Search)"}
    orr = orr.loc[[k for k in labels if k in orr.index]].assign(
        label=lambda d: d.index.map(labels)).reset_index(drop=True)
    base = alt.Chart(orr).encode(y=alt.Y("label:N", title=None, sort=alt.SortField("odds_ratio"),
                                         axis=alt.Axis(labelLimit=260)))
    pts = base.mark_point(filled=True, size=90, color=BLUE).encode(
        x=alt.X("odds_ratio:Q", title="Odds ratio (log scale, 95% CI)",
                scale=alt.Scale(type="log", domain=[0.15, 2], nice=False),
                axis=alt.Axis(values=[0.2, 0.3, 0.5, 0.7, 1, 1.5, 2])),
        tooltip=[alt.Tooltip("label:N", title="Variable"),
                 alt.Tooltip("odds_ratio:Q", title="OR", format=".3f"),
                 alt.Tooltip("or_ci_low:Q", title="CI low", format=".3f"),
                 alt.Tooltip("or_ci_high:Q", title="CI high", format=".3f"),
                 alt.Tooltip("p_value:Q", title="p", format=".2e")])
    ci = base.mark_rule(color=GREY, strokeWidth=2).encode(x="or_ci_low:Q", x2="or_ci_high:Q")
    one = alt.Chart(pd.DataFrame({"x": [1]})).mark_rule(strokeDash=[4, 4],
                                                         color=ORANGE).encode(x="x:Q")
    st.altair_chart((ci + pts + one).properties(height=340), width="stretch")
    st.caption("Logistic regression, standard errors clustered by customer. Odds ratio < 1 "
               "= lower odds of repeating. These are associations from observational data, "
               "not proven causal effects. Not re-fit when filters change.")


# ===========================================================================
# RECOMMENDATIONS
# ===========================================================================
with tab_rec:
    st.subheader("Recommended actions (base case, annualised)")
    st.warning("Dollar figures assume the data is a 10% customer sample and use "
               "planning assumptions for costs and effect sizes. They show how to size "
               "an initiative, not a forecast. All effects must be validated by "
               "controlled tests before rollout.", icon="⚠️")
    bc = table("04_business_cases.csv")
    bc = bc[bc.tier.str.contains("base")].copy()
    names = {"1. Tiered service recovery": "Service recovery",
             "2. Electronics/Home post-purchase fix": "Electronics/Home post-purchase fix",
             "3. Coupon-dependency weaning": "Coupon-dependency reduction (test first)"}
    bc["Initiative"] = bc.intervention.map(names) + bc.tier.str.extract(
        r"^([AB]):")[0].map({"A": " – automated (2 tickets)",
                             "B": " – human callback (3+ tickets)"}).fillna("")
    view = bc[["Initiative", "addressable_yr", "effective_uplift_pp", "breakeven_uplift_pp",
               "incremental_gmv_yr", "cost_yr", "net_yr", "roi"]].rename(columns={
        "addressable_yr": "Addressable / yr", "effective_uplift_pp": "Uplift used (pp)",
        "breakeven_uplift_pp": "Break-even uplift (pp)",
        "incremental_gmv_yr": "Incremental GMV", "cost_yr": "Cost", "net_yr": "Net contribution",
        "roi": "Net ROI"})
    st.dataframe(view.set_index("Initiative").style.format({
        "Addressable / yr": "{:,.0f}", "Uplift used (pp)": "{:.2f}",
        "Break-even uplift (pp)": "{:.2f}", "Incremental GMV": "${:,.0f}", "Cost": "${:,.0f}",
        "Net contribution": "${:,.0f}", "Net ROI": "{:.2f}x"}), width="stretch")
    tot_net, tot_cost = bc.net_yr.sum(), bc.cost_yr.sum()
    # "\\$" stops Streamlit Markdown from reading $...$ as LaTeX
    st.markdown(f"**Portfolio:** net contribution **\\${tot_net:,.0f}** on cost "
                f"**\\${tot_cost:,.0f}** (net ROI {tot_net / tot_cost:.2f}x). "
                "13 of 18 sensitivity scenarios are value-positive; with zero repeat uplift "
                "the portfolio loses money, so the uplift must be proven.")

    st.markdown("**How each recommendation should be validated**")
    st.markdown("""
| Action | Target | Validation / success metric | Key risk |
|---|---|---|---|
| Track new-customer repeat & cohort M+1 as primary KPIs | Reporting change | Adopted in weekly reporting | None; prevents the next decline being masked |
| Service recovery at the 2nd ticket | Customers reaching 2 / 3+ tickets | 2 tickets: 10% holdout, primary metric escalations to 3+ tickets. 3+ tickets: 50/50 test (low volume), primary metric 30-day repeat | Effect size comes from a model counterfactual, not an experiment |
| Electronics/Home post-purchase fix | Electronics & Home buyers | Staged rollout by category or region; tickets per order and 30-day repeat | Largest benefit; relies on an assumed 30% ticket reduction |
| Reduce coupon dependency | 3+ order customers with ≥60% coupon history | A/B test before any rollout; repeat rate and margin per customer | Weakest causal evidence (low-intent customers may seek coupons) |
""")


# ===========================================================================
# DEFINITIONS
# ===========================================================================
with tab_def:
    st.subheader("KPI definitions")
    st.markdown("""
| KPI | Numerator | Denominator | Unit |
|---|---|---|---|
| Order-level 30-day repeat (headline) | Orders followed by the same customer's next order within 30 days | Orders placed ≥30 days before snapshot | Order |
| New-customer 30-day repeat | First-time customers with a 2nd order within 30 days | First-time customers acquired ≥30 days before snapshot | Customer |
| 90-day repeat customer rate | New customers with a 2nd order within 90 days | New customers acquired ≥90 days before snapshot | Customer |
| Cohort M+n retention | Cohort customers with ≥1 order in calendar month M+n | Customers acquired in the cohort month | Customer × month |
| Average order value | GMV | Orders (incl. zero-value comped orders) | Order |
| Purchase frequency | Orders in period | Active customers in period | Customer |
| Time to 2nd order | Days from 1st to 2nd order | Customers with a 2nd order (conditional) | Customer |
""")
    st.markdown(
        "Full definitions, including why repeat rate, retention and cohort retention are "
        "**not** interchangeable: `docs/kpi_definitions.md`.\n\n"
        "**Data.** Simulated by `src/00_make_dataset.py` (14,000 customers, "
        "2024-01-01 to 2025-06-30) with realistic data-quality problems injected, then "
        "cleaned by `src/01_clean_features.py` (97.7% of rows retained). The analysis "
        "never reads the simulator's parameters; it rediscovers the patterns from the "
        "CSV. Because the patterns were planted, the project demonstrates *method*, "
        "not real-world findings.")
    st.caption(f"Rows in current selection: {len(o_f):,} orders (order-level), "
               f"{c_f.user_id.nunique():,} customers (customer-level).")
