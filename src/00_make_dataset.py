"""
00_make_dataset.py
------------------
Builds `data/raw/orders_data.csv`.

NOTE ON PROVENANCE: no production extract was available for this exercise, so the
order log is simulated from an explicit generative model. Ground truth is baked in
here (ticket cliff, discount dependency, category repeat gradients, a service
degradation ramp starting 2024-10) and is NOT referenced by any downstream script --
Phases 1-4 rediscover it from the CSV alone. Every dirty-data pattern below was
copied from things I've actually had to clean in real order logs.

Snapshot date: 2025-06-30. Acquisition window: 2024-01-01 .. 2025-06-30.
"""

import numpy as np
import pandas as pd
from datetime import timedelta

from common import RAW

RNG = np.random.default_rng(20250630)

N_USERS = 14_000
START = pd.Timestamp("2024-01-01")
SNAPSHOT = pd.Timestamp("2025-06-30")
MAX_ORDERS_PER_USER = 40

# ---------------------------------------------------------------------------
# Generative parameters (ground truth)
# ---------------------------------------------------------------------------

CHANNELS = {
    #                 share   quality (logit shift on repeat)  discount propensity
    "Organic":      (0.24,  0.35, -0.30),
    "Email/CRM":    (0.14,  0.22,  0.25),
    "Paid Search":  (0.26,  0.02,  0.00),
    "Paid Social":  (0.24, -0.28,  0.45),
    "Affiliate":    (0.12, -0.40,  0.70),
}

CATEGORIES = {
    #              share  log-AOV mu  sd    repeat shift  return rate  incident weight
    "Electronics": (0.16, 5.30, 0.62, -0.45, 0.11, 1.80),
    "Home":        (0.18, 4.45, 0.58, -0.10, 0.08, 1.50),
    "Apparel":     (0.22, 4.05, 0.55,  0.05, 0.17, 1.00),
    "Beauty":      (0.20, 3.55, 0.48,  0.38, 0.05, 0.60),
    "Grocery":     (0.16, 3.30, 0.42,  0.52, 0.02, 0.40),
    "Sports":      (0.08, 4.20, 0.55, -0.05, 0.10, 1.20),
}

# Fulfilment/service strain multiplier by calendar month. Peak-season strain in
# 2024-Q4 never recovered -- this is the root cause the analysis should surface.
INCIDENT_MULT = {
    "2024-01": 1.00, "2024-02": 1.00, "2024-03": 1.02, "2024-04": 1.00,
    "2024-05": 1.03, "2024-06": 1.05, "2024-07": 1.02, "2024-08": 1.00,
    "2024-09": 1.05, "2024-10": 1.15, "2024-11": 1.35, "2024-12": 1.60,
    "2025-01": 1.75, "2025-02": 1.90, "2025-03": 2.00, "2025-04": 2.05,
    "2025-05": 2.10, "2025-06": 2.10,
}

# Small residual period drag on repeat intent not explained by tickets alone
# (slower delivery, more stockouts -- things the order log never records).
PERIOD_DRAG = {
    "2024-01": 0.00, "2024-02": 0.00, "2024-03": 0.00, "2024-04": -0.01,
    "2024-05": -0.01, "2024-06": -0.02, "2024-07": -0.02, "2024-08": -0.02,
    "2024-09": -0.03, "2024-10": -0.06, "2024-11": -0.10, "2024-12": -0.14,
    "2025-01": -0.18, "2025-02": -0.21, "2025-03": -0.24, "2025-04": -0.26,
    "2025-05": -0.28, "2025-06": -0.28,
}

# Promo intensity by month -- marketing leaned harder on coupons as repeat sagged.
PROMO_BASE = {
    "2024-01": 0.30, "2024-02": 0.28, "2024-03": 0.30, "2024-04": 0.31,
    "2024-05": 0.33, "2024-06": 0.40, "2024-07": 0.34, "2024-08": 0.32,
    "2024-09": 0.35, "2024-10": 0.40, "2024-11": 0.55, "2024-12": 0.58,
    "2025-01": 0.44, "2025-02": 0.43, "2025-03": 0.46, "2025-04": 0.48,
    "2025-05": 0.50, "2025-06": 0.56,
}

# Monthly acquisition volume -- paid push in H2 2024, budget cut in 2025.
ACQ_WEIGHTS = np.array([
    0.055, 0.052, 0.058, 0.056, 0.060, 0.062,   # 2024 H1
    0.058, 0.057, 0.062, 0.068, 0.078, 0.072,   # 2024 H2
    0.050, 0.046, 0.048, 0.045, 0.041, 0.032,   # 2025 H1
])
ACQ_WEIGHTS = ACQ_WEIGHTS / ACQ_WEIGHTS.sum()
ACQ_MONTHS = pd.period_range("2024-01", "2025-06", freq="M")

# Ticket-count effect on 30-day repeat. The cliff at >=3 is the headline finding.
TICKET_EFFECT = {0: 0.00, 1: -0.28, 2: -0.62}
TICKET_EFFECT_3PLUS = -1.55


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _pick(d):
    """Weighted draw from a {key: (share, ...)} spec dict."""
    keys = list(d.keys())
    p = np.array([d[k][0] for k in keys], dtype=float)
    return keys, p / p.sum()


def simulate_orders():
    ch_keys, ch_p = _pick(CHANNELS)
    cat_keys, cat_p = _pick(CATEGORIES)

    # --- assign each user an acquisition month, channel and latent quality ----
    acq_idx = RNG.choice(len(ACQ_MONTHS), size=N_USERS, p=ACQ_WEIGHTS)
    channels = RNG.choice(ch_keys, size=N_USERS, p=ch_p)
    user_effect = RNG.normal(0, 0.55, size=N_USERS)
    # Some people just contact support more, independent of how bad the order was.
    complain_prop = RNG.gamma(shape=2.0, scale=0.5, size=N_USERS)
    # Persistent category affinity: users mostly shop one or two aisles.
    home_cat = RNG.choice(cat_keys, size=N_USERS, p=cat_p)

    rows = []
    order_seq = 0

    for u in range(N_USERS):
        uid = f"U{100000 + u}"
        channel = channels[u]
        ch_quality, ch_promo = CHANNELS[channel][1], CHANNELS[channel][2]

        # First order lands uniformly inside the acquisition month
        month = ACQ_MONTHS[acq_idx[u]]
        m_start, m_end = month.start_time, month.end_time
        t = m_start + timedelta(seconds=float(RNG.uniform(0, (m_end - m_start).total_seconds())))

        prior_orders = 0
        discount_count = 0
        prev_returned = 0

        while t <= SNAPSHOT and prior_orders < MAX_ORDERS_PER_USER:
            mkey = t.strftime("%Y-%m")
            incident_mult = INCIDENT_MULT[mkey]

            # --- category: 62% chance of staying in the home aisle ------------
            if RNG.random() < 0.62:
                category = home_cat[u]
            else:
                category = RNG.choice(cat_keys, p=cat_p)
            _, aov_mu, aov_sd, cat_repeat, cat_ret, cat_incident = CATEGORIES[category]

            # --- order amount -------------------------------------------------
            amount = float(RNG.lognormal(aov_mu, aov_sd))
            # Repeat buyers trend slightly larger baskets
            amount *= 1.0 + 0.03 * min(prior_orders, 8)

            # --- coupon usage ---------------------------------------------------
            p_disc = _sigmoid(
                np.log(PROMO_BASE[mkey] / (1 - PROMO_BASE[mkey]))
                + ch_promo
                + 0.25 * (discount_count / max(prior_orders, 1) - 0.35) * 2
            )
            discount_used = int(RNG.random() < p_disc)

            # --- return ---------------------------------------------------------
            p_return = cat_ret * (0.85 + 0.35 * incident_mult)
            is_returned = int(RNG.random() < min(p_return, 0.45))

            # --- support contacts in the trailing 30 days ------------------------
            lam = (
                0.16
                * incident_mult
                * cat_incident
                * complain_prop[u]
                * (1.0 + 0.9 * prev_returned)
            )
            cs_tickets = int(RNG.poisson(lam))

            rows.append(
                {
                    "order_id": f"O{900000 + order_seq}",
                    "user_id": uid,
                    "order_date": t,
                    "order_amount": round(amount, 2),
                    "category": category,
                    "discount_used": discount_used,
                    "cs_tickets": cs_tickets,
                    "is_returned": is_returned,
                    "channel": channel,
                }
            )
            order_seq += 1

            # --- will they order again within 30 days? ---------------------------
            disc_rate = (discount_count + discount_used) / (prior_orders + 1)
            z_amt = (np.log(amount) - 4.2) / 0.7

            if cs_tickets >= 3:
                tick_eff = TICKET_EFFECT_3PLUS
            else:
                tick_eff = TICKET_EFFECT[cs_tickets]

            lp = (
                -0.15
                + ch_quality
                + cat_repeat
                + user_effect[u]
                + 0.30 * np.log1p(prior_orders)
                - 0.15 * z_amt
                + tick_eff
                - 0.85 * (disc_rate - 0.35)
                - 0.22 * is_returned
                + PERIOD_DRAG[mkey]
            )
            p_repeat_30 = _sigmoid(lp)

            prior_orders += 1
            discount_count += discount_used
            prev_returned = is_returned

            if RNG.random() < p_repeat_30:
                gap = 1 + int(29 * RNG.beta(1.6, 2.2))
            else:
                # Not within 30 days -- either a slow return or a real churn
                p_late = _sigmoid(lp - 0.9)
                if RNG.random() < p_late:
                    gap = 31 + int(RNG.gamma(2.0, 28.0))
                else:
                    break
            t = t + timedelta(days=gap, seconds=float(RNG.uniform(0, 86400)))

    return pd.DataFrame(rows)


def dirty_it_up(df):
    """Inject the data-quality problems a real export would carry."""
    df = df.copy()
    n = len(df)
    log = []

    # 1. Exact duplicate rows -- double-submitted checkout events (~1.8%)
    dup_idx = RNG.choice(n, size=int(0.018 * n), replace=False)
    dupes = df.iloc[dup_idx].copy()
    df = pd.concat([df, dupes], ignore_index=True)
    log.append(f"injected {len(dupes)} duplicate rows")

    # 2. Category casing / whitespace drift from a warehouse migration
    cat_idx = RNG.choice(len(df), size=int(0.07 * len(df)), replace=False)
    variants = [str.lower, str.upper, lambda s: f"  {s} ", lambda s: f"{s}_"]
    for i in cat_idx:
        f = variants[RNG.integers(0, len(variants))]
        df.at[i, "category"] = f(df.at[i, "category"])
    log.append(f"scrambled casing/whitespace on {len(cat_idx)} category values")

    # 3. Missing order_amount (~2.5%) and missing category (~1.2%)
    amt_null = RNG.choice(len(df), size=int(0.025 * len(df)), replace=False)
    df.loc[amt_null, "order_amount"] = np.nan
    cat_null = RNG.choice(len(df), size=int(0.012 * len(df)), replace=False)
    df.loc[cat_null[: len(cat_null) // 2], "category"] = np.nan
    df.loc[cat_null[len(cat_null) // 2:], "category"] = ""
    log.append(f"nulled {len(amt_null)} amounts, {len(cat_null)} categories")

    # 4. Refund rows logged with the wrong sign (~0.4%)
    neg_idx = RNG.choice(len(df), size=int(0.004 * len(df)), replace=False)
    df.loc[neg_idx, "order_amount"] = -df.loc[neg_idx, "order_amount"].abs()
    log.append(f"sign-flipped {len(neg_idx)} amounts")

    # 5. Zero-value rows (fully comped orders)
    zero_idx = RNG.choice(len(df), size=int(0.003 * len(df)), replace=False)
    df.loc[zero_idx, "order_amount"] = 0.0
    log.append(f"zeroed {len(zero_idx)} amounts")

    # 6. QA/load-test orders on internal accounts
    n_test = 120
    test_rows = df.sample(n_test, random_state=7).copy()
    test_rows["user_id"] = [f"TEST_{i:03d}" for i in range(n_test)]
    test_rows["order_amount"] = RNG.uniform(19000, 60000, size=n_test).round(2)
    test_rows["order_id"] = [f"OTEST{i:04d}" for i in range(n_test)]
    df = pd.concat([df, test_rows], ignore_index=True)
    log.append(f"injected {n_test} internal QA orders with absurd amounts")

    # 7. cs_tickets sentinel -1 for "unknown" from the legacy CRM
    tick_idx = RNG.choice(len(df), size=int(0.009 * len(df)), replace=False)
    df.loc[tick_idx, "cs_tickets"] = -1
    log.append(f"set {len(tick_idx)} cs_tickets to sentinel -1")

    # 8. Future-dated orders from a clock-skew bug on one app server
    fut_idx = RNG.choice(len(df), size=int(0.003 * len(df)), replace=False)
    df.loc[fut_idx, "order_date"] = SNAPSHOT + pd.to_timedelta(
        RNG.integers(30, 400, size=len(fut_idx)), unit="D"
    )
    log.append(f"pushed {len(fut_idx)} order_dates past the snapshot")

    # 9. Mixed date string formats
    df["order_date"] = pd.to_datetime(df["order_date"])
    df = df.sort_values("order_date").reset_index(drop=True)
    iso = df["order_date"].dt.strftime("%Y-%m-%d %H:%M:%S").to_numpy(dtype=object)
    us = df["order_date"].dt.strftime("%m/%d/%Y %H:%M").to_numpy(dtype=object)
    us_idx = RNG.choice(len(df), size=int(0.05 * len(df)), replace=False)
    iso[us_idx] = us[us_idx]
    df["order_date"] = iso
    log.append(f"rewrote {len(us_idx)} dates in US M/D/Y format")

    # 10. discount_used stored as mixed types by one upstream service
    bool_idx = RNG.choice(len(df), size=int(0.04 * len(df)), replace=False)
    df["discount_used"] = df["discount_used"].astype(object)
    df.loc[bool_idx, "discount_used"] = df.loc[bool_idx, "discount_used"].map(
        {0: "N", 1: "Y"}
    )
    log.append(f"rewrote {len(bool_idx)} discount_used values as Y/N")

    df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)
    return df, log


if __name__ == "__main__":
    clean = simulate_orders()
    print(f"simulated {len(clean):,} orders / {clean.user_id.nunique():,} users")

    raw, log = dirty_it_up(clean)
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / "orders_data.csv"
    raw.to_csv(out, index=False)

    print(f"wrote {out}: {len(raw):,} rows x {raw.shape[1]} cols")
    for line in log:
        print("  -", line)
