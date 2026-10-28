"""
Single source of truth for KPI definitions.

Imported by 05_kpis_robustness.py, 06_sql_checks.py and the Streamlit dashboard,
so a KPI shown on the dashboard is computed by exactly the same code as the one
quoted in REPORT.md. Every function takes the cleaned order table produced by
01_clean_features.py (data/processed/orders_clean.csv) and returns plain numbers
or DataFrames -- no plotting, no I/O side effects.

Counting units matter and are deliberately different between metrics:
  * order_repeat_rate        -- unit = ORDER  (composition-weighted, the "headline")
  * new_customer_repeat_rate -- unit = NEW CUSTOMER (first order only)
  * cohort_retention         -- unit = CUSTOMER x CALENDAR MONTH
  * repeat_customer_rate     -- unit = CUSTOMER with a fixed observation window
These are not interchangeable; docs/kpi_definitions.md explains why.
"""

import numpy as np
import pandas as pd

from common import PROC, SNAPSHOT, REPEAT_WINDOW


def load_orders(path=None):
    """Cleaned order table with dates parsed."""
    path = path or PROC / "orders_clean.csv"
    return pd.read_csv(path, parse_dates=["order_date", "prev_date", "next_date"])


def first_orders(orders):
    """One row per customer: their first observed order."""
    return orders[orders["order_seq"] == 0]


# ---------------------------------------------------------------------------
# Repeat / retention
# ---------------------------------------------------------------------------
def order_repeat_rate(orders, window=REPEAT_WINDOW):
    """Share of orders followed by another order from the same customer within
    `window` days. Only orders placed >= `window` days before the snapshot are
    scoreable (right-censoring). Returns (numerator, denominator, rate)."""
    scoreable = orders[orders["order_date"] <= SNAPSHOT - pd.Timedelta(days=window)]
    num = int((scoreable["days_to_next"] <= window).sum())
    den = len(scoreable)
    return num, den, num / den if den else np.nan


def new_customer_repeat_rate(orders, window=REPEAT_WINDOW):
    """Share of first-time customers who place a second order within `window`
    days of their first. Customers whose first order is < `window` days before
    the snapshot are excluded (not yet observable). Returns (num, den, rate)."""
    f = first_orders(orders)
    f = f[f["order_date"] <= SNAPSHOT - pd.Timedelta(days=window)]
    num = int((f["days_to_next"] <= window).sum())
    den = len(f)
    return num, den, num / den if den else np.nan


def new_customer_repeat_by_cohort(orders, window=REPEAT_WINDOW):
    """new_customer_repeat_rate per acquisition month."""
    f = first_orders(orders)
    f = f[f["order_date"] <= SNAPSHOT - pd.Timedelta(days=window)]
    g = f.groupby("cohort_month")["days_to_next"]
    out = pd.DataFrame({
        "new_customers": g.size(),
        "repeated": g.apply(lambda s: int((s <= window).sum())),
    })
    out["new_customer_repeat"] = out["repeated"] / out["new_customers"]
    return out


def cohort_retention(orders):
    """Cohort x months-since-acquisition matrix. Cell = share of the cohort that
    placed at least one order in calendar month M+n. Months that have not yet
    happened at the snapshot are NaN. Same logic as 02_eda_cohort.py."""
    first_period = orders.groupby("user_id")["order_date"].min().dt.to_period("M")
    cohort = orders["user_id"].map(first_period)
    m_idx = (orders["order_date"].dt.to_period("M") - cohort).apply(lambda x: x.n)
    tmp = pd.DataFrame({"user_id": orders["user_id"], "cohort": cohort.astype(str),
                        "m_idx": m_idx})
    sizes = tmp.groupby("cohort")["user_id"].nunique()
    active = tmp.groupby(["cohort", "m_idx"])["user_id"].nunique().unstack(fill_value=0)
    ret = active.div(sizes, axis=0)
    for c in ret.index:
        horizon = (SNAPSHOT.to_period("M") - pd.Period(c, "M")).n
        ret.loc[c, [m for m in ret.columns if m > horizon]] = np.nan
    ret.insert(0, "cohort_size", sizes)
    return ret


def repeat_customer_rate(orders, window=90):
    """Customer-level repeat rate with a FIXED window: share of customers who
    placed a 2nd order within `window` days of their first, among customers with
    at least `window` days of observation. Unlike 'share of customers with 2+
    orders ever', this does not penalise recently acquired customers."""
    return new_customer_repeat_rate(orders, window)


# ---------------------------------------------------------------------------
# Value / frequency
# ---------------------------------------------------------------------------
def aov(orders):
    """Average order value = GMV / orders. Zero-value (comped) orders count as
    orders; winsorised/imputed amounts are used as cleaned."""
    return orders["order_amount"].sum() / len(orders) if len(orders) else np.nan


def purchase_frequency(orders):
    """Orders per customer in the selected window (not lifetime-normalised)."""
    n = orders["user_id"].nunique()
    return len(orders) / n if n else np.nan


def time_to_second_order(orders):
    """Days from first to second order, for customers who have a second order.
    Conditional on repeating -- do not read it as 'how long everyone takes'."""
    return first_orders(orders)["days_to_next"].dropna()


def first_vs_repeat_orders(orders):
    """Compare first orders with repeat orders (order_seq >= 1)."""
    o = orders.assign(order_type=np.where(orders["order_seq"] == 0,
                                          "First order", "Repeat order"))
    out = o.groupby("order_type").agg(
        orders=("order_id", "size"),
        gmv=("order_amount", "sum"),
        aov=("order_amount", "mean"),
        coupon_share=("discount_used", "mean"),
        avg_tickets=("cs_tickets", "mean"),
        return_rate=("is_returned", "mean"),
    )
    out["gmv_share"] = out["gmv"] / out["gmv"].sum()
    return out


def kpi_snapshot(orders):
    """Headline KPI set for an (optionally filtered) order table."""
    o_num, o_den, o_rate = order_repeat_rate(orders)
    n_num, n_den, n_rate = new_customer_repeat_rate(orders)
    r_num, r_den, r_rate = repeat_customer_rate(orders, 90)
    tts = time_to_second_order(orders)
    return {
        "orders": len(orders),
        "customers": orders["user_id"].nunique(),
        "gmv": float(orders["order_amount"].sum()),
        "aov": aov(orders),
        "purchase_frequency": purchase_frequency(orders),
        "order_repeat_30d": o_rate, "order_repeat_30d_num": o_num, "order_repeat_30d_den": o_den,
        "new_customer_repeat_30d": n_rate, "new_customer_repeat_30d_num": n_num,
        "new_customer_repeat_30d_den": n_den,
        "repeat_customer_90d": r_rate, "repeat_customer_90d_num": r_num,
        "repeat_customer_90d_den": r_den,
        "median_days_to_2nd": float(tts.median()) if len(tts) else np.nan,
    }
