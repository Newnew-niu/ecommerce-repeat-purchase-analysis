"""Shared paths, constants and small helpers used across the analysis scripts."""

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
FIG = ROOT / "outputs" / "figures"
TAB = ROOT / "outputs" / "tables"
LOGS = ROOT / "logs"

for _p in (PROC, FIG, TAB, LOGS):
    _p.mkdir(parents=True, exist_ok=True)

# Data snapshot: the last date we can trust the extract to be complete.
SNAPSHOT = pd.Timestamp("2025-06-30")

# Primary KPI horizon. An order is "repeated" if the same user places another
# order within REPEAT_WINDOW days of it.
REPEAT_WINDOW = 30

# Contribution margin used for all GMV -> profit conversions in Phase 4.
# Blended across categories, net of payment fees and reverse logistics.
GROSS_MARGIN = 0.42

CATEGORY_ORDER = ["Grocery", "Beauty", "Apparel", "Sports", "Home", "Electronics"]


class Tee:
    """Print to stdout and accumulate into a log file at the same time."""

    def __init__(self, path):
        self.path = Path(path)
        self.lines = []

    def __call__(self, msg=""):
        print(msg)
        self.lines.append(str(msg))

    def save(self):
        self.path.write_text("\n".join(self.lines), encoding="utf-8")
        print(f"\n[log written] {self.path}")


def pct(x, digits=1):
    return f"{100 * x:.{digits}f}%"


def usd(x):
    return f"${x:,.0f}"
