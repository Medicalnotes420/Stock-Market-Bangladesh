"""DSEX by month, year to year, and around elections and pay scales, exactly as docs/CALENDAR_EVENTS_PREREG.md.
Run from the repo root: python scripts/calendar_events.py
Output: results/calendar_months.csv, results/calendar_events.csv and a printed summary."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsex_history import floor_mask  # noqa: E402

T_BAR, HALF_SPLIT, WIN = 3.0, 2020, 60
ELECTIONS = ["2014-01-05", "2018-12-30", "2024-01-07", "2026-02-12"]  # daily data; 2001, 2008 yearly only
ELECTION_YEARS = [2001, 2008, 2014, 2018, 2024]
PAY_SCALES = ["2015-09-07", "2026-08-31"]  # cabinet approval of the 8th and 9th scales


def welch_t(a, b):
    return (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))


def spearman_perm(x, y, n=10000, seed=1):
    """Spearman rho and a two-sided p from shuffling y (no scipy in this project)."""
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    rho = np.corrcoef(rx, ry)[0, 1]
    rng = np.random.default_rng(seed)
    null = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(n)])
    return rho, (np.abs(null) >= abs(rho)).mean()


def month_changes(s):
    """Per calendar month: sum of daily log changes, dropping months where over half the sessions are floor/missing."""
    r = np.log(s).diff()
    r[s.index.to_series().diff().dt.days > 7] = np.nan
    r[floor_mask(s.index)] = np.nan
    g = r.groupby([r.index.year, r.index.month])
    ok = g.count() >= g.size() / 2
    out = g.sum()[ok]
    out.index.names = ["year", "month"]
    return out.rename("change").reset_index()


def month_test(m):
    rows = []
    for mo in range(1, 13):
        a, b = m[m.month == mo].change, m[m.month != mo].change
        t = welch_t(a, b)
        halves = [m[(m.month == mo) & sel].change.mean() - m[(m.month != mo) & sel].change.mean()
                  for sel in (m.year < HALF_SPLIT, m.year >= HALF_SPLIT)]
        same = np.sign(halves[0]) == np.sign(halves[1]) == np.sign(a.mean() - b.mean())
        verdict = "PATTERN" if abs(t) >= T_BAR and same else "HINT" if abs(t) >= 2 and same else "NONE"
        rows.append({"month": mo, "n": len(a), "mean_pct": 100 * a.mean(), "others_pct": 100 * b.mean(),
                     "up_share": (a > 0).mean(), "t": t, "half1_diff_pct": 100 * halves[0],
                     "half2_diff_pct": 100 * halves[1], "verdict": verdict})
    return pd.DataFrame(rows)


def around(s, date, win=WIN):
    """DSEX change over `win` sessions before and after `date`, and each one's percentile among all such windows."""
    i = s.index.searchsorted(pd.Timestamp(date))
    allw = (s / s.shift(win) - 1).dropna()
    res = {"date": date}
    for side, (a, b) in {"before": (i - win, i), "after": (i, i + win)}.items():
        if a < 0 or b >= len(s):
            res[side + "_pct"], res[side + "_pctile"] = np.nan, np.nan
            continue
        ch = s.iloc[b] / s.iloc[a] - 1
        res[side + "_pct"], res[side + "_pctile"] = 100 * ch, 100 * (allw < ch).mean()
    return res


if __name__ == "__main__":
    mk = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date")
    s = mk.dsex.dropna()
    M = month_test(month_changes(s))
    y = pd.read_csv("results/dse_long_run.csv").set_index("year").return_bdt_pct.dropna()
    rho, p = spearman_perm(y.iloc[:-1].to_numpy(), y.iloc[1:].to_numpy())
    E = pd.DataFrame([dict(around(s, d), kind="election") for d in ELECTIONS] +
                     [dict(around(s, d), kind="pay scale") for d in PAY_SCALES])
    Path("results").mkdir(exist_ok=True)
    M.to_csv("results/calendar_months.csv", index=False)
    E.to_csv("results/calendar_events.csv", index=False)
    pd.set_option("display.width", 200)
    print("T1 month of the year (DSEX, floor days out):")
    print(M.round(2).to_string(index=False))
    print(f"\nT2 good year after good year (1997-2025, {len(y) - 1} pairs): Spearman {rho:+.2f}, p {p:.2f} -> "
          + ("YES" if p < 0.05 else "NO"))
    print("\nT3 around events, 60 sessions (percentile among all 60-session moves):")
    print(E.round(1).to_string(index=False))
    ey = y[y.index.isin(ELECTION_YEARS)]
    print(f"Election years {list(ey.index)}: mean {ey.mean():+.1f}% vs other years {y[~y.index.isin(ELECTION_YEARS)].mean():+.1f}%"
          f" ({', '.join(f'{k} {v:+.0f}%' for k, v in ey.items())})")
