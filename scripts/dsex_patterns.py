"""DSEX market-level pattern test, exactly as docs/DSEX_PATTERNS_PREREG.md.
Run from the repo root: python scripts/dsex_patterns.py
Output: results/dsex_patterns.csv and a printed table."""
from pathlib import Path

import numpy as np
import pandas as pd

PERIODS = {"A": ("2014-01-01", "2022-12-31"), "B": ("2023-01-01", "2026-01-22"),
           "C": ("2026-01-25", "2026-11-04"), "D": ("2026-11-05", "2099-12-31")}
FLOOR = [("2020-03-19", "2021-04-07"), ("2022-07-28", "2024-01-21")]  # same as scripts/run_phase4.py
T_MIN, COST, D_MIN = 2.50, 0.011, 120
SIGN = {"MOM1": +1, "DOWN3": -1, "BR1": +1, "SUN": -1}


def pattern_values(m):
    """m: DataFrame[dsex, adv, dec] indexed by date. Returns {test: Series of x by session} (SUN is raw Sunday r)."""
    r = np.log(m.dsex).diff()
    r[m.index.to_series().diff().dt.days > 7] = np.nan
    floor = np.zeros(len(m), bool)
    for a, b in FLOOR:
        floor |= (m.index >= a) & (m.index <= b)
    r[floor] = np.nan
    nxt = r.shift(-1)
    b = (m.adv - m.dec) / (m.adv + m.dec)
    down3 = (r < 0) & (r.shift(1) < 0) & (r.shift(2) < 0)
    sun = m.index.dayofweek == 6
    return {"MOM1": (np.sign(r) * nxt).dropna(),
            "DOWN3": nxt[down3].dropna(),
            "BR1": (np.sign(b) * nxt).dropna(),
            "SUN": r[sun].dropna(),
            "_other": r[~sun].dropna()}


def stats(x, other=None):
    if len(x) < 3:
        return len(x), np.nan, np.nan
    mean = x.mean() - (other.mean() if other is not None else 0)
    return len(x), mean, mean / (x.std(ddof=1) / np.sqrt(len(x)))


# self-check: a series that always continues its direction must give MOM1 > 0 and DOWN3 < 0
_d = pd.bdate_range("2015-01-01", periods=12)
_t = pd.DataFrame({"dsex": 100 * np.exp(np.cumsum([0, -.01, -.01, -.01, -.01, -.01, .01, .01, .01, .01, .01, .01])),
                   "adv": 1.0, "dec": 0.0}, index=_d)
_v = pattern_values(_t)
assert _v["MOM1"].mean() > 0 and len(_v["DOWN3"]) == 3 and _v["DOWN3"].mean() < 0 and _v["BR1"].notna().all()

if __name__ == "__main__":
    m = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date")
    vals = pattern_values(m)
    rows = []
    for test, sgn in SIGN.items():
        for per, (a, b) in PERIODS.items():
            sl = lambda s: s[(s.index >= a) & (s.index <= b)]  # noqa: E731
            n, mean, t = stats(sl(vals[test]), sl(vals["_other"]) if test == "SUN" else None)
            rows.append({"test": test, "predicts": "up" if sgn > 0 else "down", "period": per, "n": n,
                         "mean": mean, "t": t})
    res = pd.DataFrame(rows)

    def verdict(g):
        g, s = g.set_index("period"), SIGN[g.name]
        a_ok = s * g.at["A", "mean"] > 0 and abs(g.at["A", "t"]) >= T_MIN
        rest = all(g.at[k, "n"] > 0 and s * g.at[k, "mean"] > 0 for k in "BC")
        conf = g.at["D", "n"] >= D_MIN and s * g.at["D", "mean"] > 0
        return pd.Series({"verdict": ("HOLDS" if rest else "WEAK") if a_ok else "NO",
                          "tradable": abs(g.at["A", "mean"]) >= COST,
                          "confirmed_on_D": bool(conf)})

    v = res.groupby("test", sort=False).apply(verdict)
    res = res.merge(v, left_on="test", right_index=True)
    Path("results").mkdir(exist_ok=True)
    res.to_csv("results/dsex_patterns.csv", index=False)
    pd.set_option("display.width", 200)
    print(res.pivot_table(index=["test", "predicts", "verdict", "tradable", "confirmed_on_D"], columns="period",
                          values=["n", "mean", "t"], sort=False).round(5).to_string())
