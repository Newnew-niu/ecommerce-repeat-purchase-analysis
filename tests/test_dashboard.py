"""
Smoke tests for the Streamlit dashboard (headless, no browser).

    python -m pytest tests/      # or: python tests/test_dashboard.py

Requires the processed data (run `python src/run_all.py` first).
"""

import sys
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "dashboard" / "app.py")
sys.path.insert(0, str(ROOT / "src"))
import kpis  # noqa: E402


def run(**widgets):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    for label, value in widgets.items():
        w = next(x for x in at.sidebar if getattr(x, "label", None) == label)
        w.set_value(value)
    if widgets:
        at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def test_default_view_matches_analysis():
    at = run()
    orders = kpis.load_orders()
    snap = kpis.kpi_snapshot(orders)
    assert metric(at, "Orders") == f"{snap['orders']:,}"
    assert metric(at, "New-customer 30-day repeat") == f"{100 * snap['new_customer_repeat_30d']:.1f}%"
    # Same number as the KPI table written by 05_kpis_robustness.py
    kt = pd.read_csv(ROOT / "outputs" / "tables" / "05_kpi_summary.csv")
    v = kt[(kt.scope.str.startswith("Full")) & (kt.kpi == "Order-level 30-day repeat rate (headline)")].value.iat[0]
    assert metric(at, "Order-level 30-day repeat (headline)") == f"{100 * v:.1f}%"
    assert len(at.tabs) == 6


def test_filters_run_without_errors():
    run(**{"Month range": ("2025-01", "2025-06")})
    run(**{"Acquisition channel": ["Organic"]})
    run(**{"Category": ["Electronics"]})


def test_empty_selection_is_handled():
    at = run(**{"Category": []})
    assert at.warning


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
