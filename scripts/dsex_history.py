"""DSEX over its whole history in this repo (Oct 2012 on): yearly returns, swings, turnover and the big falls.
Run from the repo root: python scripts/dsex_history.py
Output: results/dsex_years.csv, results/dsex_drawdowns.csv and a printed summary.
DSEX is a price index (dividends not included); figures are in nominal taka, before inflation."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsex_patterns import FLOOR  # noqa: E402

DD_MIN = 0.20  # a "big fall": 20%+ from a closing high


def floor_mask(idx):
    m = np.zeros(len(idx), bool)
    for a, b in FLOOR:
        m |= (idx >= a) & (idx <= b)
    return m


def drawdowns(s, min_depth=DD_MIN):
    """Falls of min_depth or more from a closing high: peak, trough, depth, recovery date (None if not yet)."""
    out, peak_d, peak, trough_d, trough = [], s.index[0], s.iloc[0], None, None
    for d, v in s.items():
        if v >= peak:
            if trough is not None and 1 - trough / peak >= min_depth:
                out.append((peak_d, peak, trough_d, trough, d))
            peak_d, peak, trough_d, trough = d, v, None, None
        elif trough is None or v < trough:
            trough_d, trough = d, v
    if trough is not None and 1 - trough / peak >= min_depth:
        out.append((peak_d, peak, trough_d, trough, None))
    return pd.DataFrame([{"peak_date": a, "peak": p, "trough_date": b, "trough": t, "depth": 1 - t / p,
                          "fall_sessions": int(((s.index > a) & (s.index <= b)).sum()), "recovered": r}
                         for a, p, b, t, r in out])


def years(m):
    s = m.dsex
    r = np.log(s).diff()
    r[floor_mask(s.index)] = np.nan  # floor-price days: prices were held up, so swings there are not real
    rows = []
    for y, g in s.groupby(s.index.year):
        prev = s[s.index.year < y]
        start = prev.iloc[-1] if len(prev) else g.iloc[0]
        rows.append({"year": y, "sessions": len(g), "start": start, "end": g.iloc[-1], "return": g.iloc[-1] / start - 1,
                     "high": g.max(), "low": g.min(), "max_fall": float((1 - g / g.cummax()).max()),
                     "volatility": float(r[g.index].std() * np.sqrt(240)),
                     "turnover_cr": float(m.turnover[g.index].mean() / 1e7),
                     "floor_sessions": int(floor_mask(g.index).sum()), "partial": y == s.index[0].year})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    m = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date")
    m = m[m.dsex.notna()]  # real index days only; proxy-filled gaps are not used here
    Y, D = years(m), drawdowns(m.dsex)
    Path("results").mkdir(exist_ok=True)
    Y.to_csv("results/dsex_years.csv", index=False)
    D.to_csv("results/dsex_drawdowns.csv", index=False)
    s = m.dsex
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    full = Y[~Y.partial & (Y.year < s.index[-1].year)]
    print(f"DSEX {s.index[0]:%d %b %Y} {s.iloc[0]:,.0f} -> {s.index[-1]:%d %b %Y} {s.iloc[-1]:,.0f}: "
          f"{s.iloc[-1] / s.iloc[0] - 1:+.0%} over {yrs:.1f} years ({(s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1:+.1%} a year), "
          f"high {s.max():,.0f} on {s.idxmax():%d %b %Y}, low {s.min():,.0f} on {s.idxmin():%d %b %Y}")
    print(f"Full years up: {(full['return'] > 0).sum()} of {len(full)}; best {full.loc[full['return'].idxmax(), 'year']} "
          f"{full['return'].max():+.0%}, worst {full.loc[full['return'].idxmin(), 'year']} {full['return'].min():+.0%}")
    pd.set_option("display.width", 200)
    show = Y.assign(**{c: (Y[c] * 100).round(1) for c in ("return", "max_fall", "volatility")}).round(0)
    print(show.drop(columns="partial").to_string(index=False))
    print("\nFalls of 20%+ from a high:")
    print(D.assign(depth=(D.depth * 100).round(1), peak=D.peak.round(0), trough=D.trough.round(0))
          .to_string(index=False) if len(D) else "none")
