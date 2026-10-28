"""
Phase 6 -- SQL cross-check of the core KPIs.

Reads  : data/processed/orders_clean.csv, sql/kpi_queries.sql,
         outputs/tables/{02_monthly_trend,02_cohort_retention}.csv
Writes : outputs/tables/06_sql_check_results.csv, logs/06_sql_checks_log.txt

Loads only the raw order columns into an in-memory SQLite database, runs the
queries in sql/kpi_queries.sql, and compares every result with the pandas
pipeline. The SQL derives "next order" with LEAD() rather than reading the
pandas-engineered columns, so a match means two independent implementations
agree. Exits non-zero if any check fails, so it can gate CI.
"""

import re
import sqlite3
import sys

import numpy as np
import pandas as pd

from common import ROOT, TAB, LOGS, SNAPSHOT, REPEAT_WINDOW, Tee
import kpis

log = Tee(LOGS / "06_sql_checks_log.txt")
# Absolute tolerance for rates; relative tolerance absorbs float summation-order
# noise on large money totals (e.g. GMV ~ $3.6M differs at ~1e-8 absolute).
TOL, RTOL = 1e-9, 1e-12

log("=" * 78)
log("PHASE 6 -- SQL CROSS-CHECK")
log("=" * 78)

# --- load ---------------------------------------------------------------------
orders = kpis.load_orders()
raw = orders[["order_id", "user_id", "order_date", "order_amount", "category"]].copy()
raw["order_date"] = raw["order_date"].dt.strftime("%Y-%m-%d %H:%M:%S")

con = sqlite3.connect(":memory:")
raw.to_sql("orders", con, index=False)
log(f"\nSQLite {sqlite3.sqlite_version}: loaded {len(raw):,} orders (raw columns only)")

sql_text = (ROOT / "sql" / "kpi_queries.sql").read_text(encoding="utf-8")
queries = {m.group(1): m.group(2).strip()
           for m in re.finditer(r"-- name: (\w+)\n(.*?)(?=\n-- name: |\Z)", sql_text, re.S)}
params = {"censor_cutoff": str(SNAPSHOT - pd.Timedelta(days=REPEAT_WINDOW))}
log(f"Queries found: {', '.join(queries)}")
log(f"Censoring cutoff: {params['censor_cutoff']}")

con.executescript(queries.pop("order_sequence"))


def q(name):
    return pd.read_sql_query(queries[name], con, params=params)


results = []


def check(name, sql_vals, py_vals):
    sql_vals = np.asarray(sql_vals, dtype=float)
    py_vals = np.asarray(py_vals, dtype=float)
    ok = sql_vals.shape == py_vals.shape and np.allclose(sql_vals, py_vals, atol=TOL, rtol=RTOL)
    diff = float(np.max(np.abs(sql_vals - py_vals))) if sql_vals.shape == py_vals.shape else np.nan
    results.append({"check": name, "n_values": int(py_vals.size), "max_abs_diff": diff,
                    "passed": bool(ok)})
    log(f"  [{'PASS' if ok else 'FAIL'}] {name:<52} n={py_vals.size:<4} max|diff|={diff:.2e}")


log("\n--- Checks (tolerance 1e-9) ---")

# 1. Overall KPIs vs kpis.py
ov = q("overall_kpis").iloc[0]
snap = kpis.kpi_snapshot(orders)
check("overall: orders, customers, GMV, AOV, frequency",
      [ov.orders, ov.customers, ov.gmv, ov.aov, ov.purchase_frequency],
      [snap["orders"], snap["customers"], snap["gmv"], snap["aov"], snap["purchase_frequency"]])

# 2. Headline repeat by month vs Phase 2 table (rounded to 4 dp there)
trend = pd.read_csv(TAB / "02_monthly_trend.csv", index_col=0)
hl = q("headline_repeat_by_month").set_index("order_month")
check("headline repeat: order counts by month", hl.orders, trend.loc[hl.index, "orders"])
check("headline repeat: rate by month (vs 4dp table)",
      hl.headline_repeat.round(4), trend.loc[hl.index, "headline_repeat"])

# 3. New-customer repeat by cohort vs Phase 2 table and kpis.py
nc = q("new_customer_repeat_by_cohort").set_index("cohort_month")
check("new-customer repeat: cohort sizes", nc.new_users, trend.loc[nc.index, "new_users"])
check("new-customer repeat: rate by cohort (vs 4dp table)",
      nc.new_user_repeat.round(4), trend.loc[nc.index, "new_user_repeat"])
py_nc = kpis.new_customer_repeat_by_cohort(orders)
check("new-customer repeat: rate by cohort (vs kpis.py, exact)",
      nc.new_user_repeat, py_nc.loc[nc.index, "new_customer_repeat"])

# 4. Cohort M+1 retention vs Phase 2 matrix
ret = pd.read_csv(TAB / "02_cohort_retention.csv", index_col=0)
m1 = q("cohort_m1_retention").set_index("cohort")
check("cohort M+1 retention (vs 02_cohort_retention.csv)", m1.m1_retention,
      ret.loc[m1.index, "1"])

# 5. AOV by category
cat = q("aov_by_category").set_index("category")
py_cat = orders.groupby("category")["order_amount"].mean()
check("AOV by category", cat.aov, py_cat.loc[cat.index])

# 6. Median time to second order
med = q("time_to_second_order").iloc[0, 0]
check("median days to 2nd order", [med], [kpis.time_to_second_order(orders).median()])

res = pd.DataFrame(results)
res.to_csv(TAB / "06_sql_check_results.csv", index=False)
n_fail = int((~res.passed).sum())
log(f"\n{len(res) - n_fail}/{len(res)} checks passed.")
log.save()
sys.exit(1 if n_fail else 0)
