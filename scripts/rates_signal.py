"""Do rising bond yields come before weaker DSEX? Exactly as docs/RATES_SIGNAL_PREREG.md.
Run from the repo root (after scripts/rates_vs_index.py): python -W ignore scripts/rates_signal.py
Output: results/rates_signal.csv and a printed verdict."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calendar_events import spearman_perm  # noqa: E402
from dsex_patterns import FLOOR  # noqa: E402

HALF_END = pd.Period("2019-12", "M")
FRESH_AFTER = pd.Period("2026-06", "M")  # the test was fixed on 2026-11-05 with bond data to June 2026


def fresh_check(d):
    """Months after FRESH_AFTER (data the test never saw): next-6-month DSEX after a yield rise vs not."""
    f = d[d.index > FRESH_AFTER]
    up, flat = f.outcome[f.signal > 0], f.outcome[f.signal <= 0]
    return {"months": len(f), "rising": len(up), "not_rising": len(flat),
            "after_rise": up.mean() if len(up) else np.nan, "after_no_rise": flat.mean() if len(flat) else np.nan,
            "agrees": bool(len(up) and len(flat) and up.mean() < flat.mean())}


def samples(m, h):
    """m: monthly DataFrame [bond_yield, dsex] indexed by Period. Rows t with signal, outcome, floor share."""
    sig = m.bond_yield - m.bond_yield.shift(h)
    out = m.dsex.shift(-h) / m.dsex - 1
    floor = pd.Series(0.0, m.index)
    for a, b in FLOOR:
        floor += ((m.index.to_timestamp() >= a) & (m.index.to_timestamp() <= b)).astype(float)
    floor_ahead = floor[::-1].rolling(h, min_periods=1).mean()[::-1].shift(-1)  # share of months t+1..t+h in a floor
    return pd.DataFrame({"signal": sig, "outcome": out, "floor_share": floor_ahead}).dropna()


def by_start(d, h):
    """Non-overlapping subsamples, one per start month; Spearman + shuffle p for each."""
    rows = []
    for k in range(h):
        x = d.iloc[k::h]
        rho, p = spearman_perm(x.signal, x.outcome) if len(x) > 3 else (np.nan, np.nan)
        rows.append({"h": h, "start": k, "n": len(x), "rho": rho, "p": p,
                     "up_when_rising": x.outcome[x.signal > 0].mean(), "up_when_not": x.outcome[x.signal <= 0].mean()})
    return pd.DataFrame(rows)


def verdict(r6, r12, halves):
    every_neg = (r6.rho < 0).all()
    if every_neg and r6.p.median() < 0.05 and r12.rho.median() < 0 and all(v < 0 for v in halves):
        return "HOLDS IN-SAMPLE"
    return "WEAK" if every_neg else "NO"


if __name__ == "__main__":
    r = pd.read_csv("results/rates_monthly.csv")
    r["month"] = pd.PeriodIndex(r.month, freq="M")
    m = r.set_index("month")[["bond_yield", "dsex"]]
    m = m[m.index >= pd.Period("2012-10", "M")]
    d6, d12 = samples(m, 6), samples(m, 12)
    r6, r12 = by_start(d6, 6), by_start(d12, 12)
    halves = [by_start(d6[d6.index <= HALF_END], 6).rho.median(), by_start(d6[d6.index > HALF_END], 6).rho.median()]
    nf = d6[d6.floor_share <= 0.5]
    rnf = by_start(nf, 6)
    v = verdict(r6, r12, halves)
    out = pd.concat([r6.assign(sample="all"), r12.assign(sample="all"), rnf.assign(sample="no floor")])
    out.to_csv("results/rates_signal.csv", index=False)
    pd.set_option("display.width", 200)
    print(out.round(3).to_string(index=False))
    print(f"\nh=6: {len(d6)} months, {r6.n.min()}-{r6.n.max()} per start; rho all negative: {(r6.rho < 0).all()}; "
          f"median rho {r6.rho.median():+.2f}, median p {r6.p.median():.3f}")
    print(f"h=12: median rho {r12.rho.median():+.2f}, median p {r12.p.median():.3f}")
    print(f"halves (h=6 median rho): to 2019 {halves[0]:+.2f}, from 2020 {halves[1]:+.2f}")
    print(f"no-floor sensitivity (h=6): median rho {rnf.rho.median():+.2f}, median p {rnf.p.median():.3f}")
    print(f"next 6 months when yields rose: {100 * d6.outcome[d6.signal > 0].mean():+.1f}% vs "
          f"{100 * d6.outcome[d6.signal <= 0].mean():+.1f}% when not (all months, overlapping)")
    print("Verdict:", v, "(in-sample, fixed 2026-11-05)")
    fc = fresh_check(d6)
    if fc["months"] == 0:
        print(f"Fresh months after {FRESH_AFTER}: none complete yet (each needs 6 more months of DSEX).")
    else:
        print(f"Fresh months after {FRESH_AFTER}: {fc['months']} ({fc['rising']} after a yield rise, "
              f"{fc['not_rising']} not). Next 6 months: {100 * fc['after_rise']:+.1f}% after a rise vs "
              f"{100 * fc['after_no_rise']:+.1f}% otherwise -> "
              + ("agrees with the link" if fc["agrees"] else "does not agree yet (or too few of one kind)")
              + ". Overlapping months: read as a running tally, not a test.")
