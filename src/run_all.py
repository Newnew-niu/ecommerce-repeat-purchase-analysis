"""
Run the full pipeline in order: data generation -> cleaning -> EDA -> models ->
business case -> KPI/robustness -> SQL cross-check.

    python src/run_all.py

Stops at the first failing step. Total runtime ~1-2 minutes.
"""

import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
STEPS = [
    "00_make_dataset.py",
    "01_clean_features.py",
    "02_eda_cohort.py",
    "03_modeling.py",
    "04_roi.py",
    "05_kpis_robustness.py",
    "06_sql_checks.py",
]

for step in STEPS:
    t0 = time.time()
    print(f"--> {step}", flush=True)
    r = subprocess.run([sys.executable, step], cwd=SRC, stdout=subprocess.DEVNULL)
    if r.returncode:
        sys.exit(f"FAILED: {step} (exit {r.returncode}). Re-run it directly to see output.")
    print(f"    done in {time.time() - t0:.0f}s", flush=True)

print("\nAll steps completed. Logs: logs/  Results: outputs/")
