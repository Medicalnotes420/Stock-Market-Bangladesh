"""Does a deep fall predict a big rise? Exactly as docs/DEEP_LOW_PREREG.md.
Run from the repo root: python scripts/deep_low.py  -> results/deep_low_years.csv, results/deep_low_episodes.csv"""
from pathlib import Path

import numpy as np
import pandas as pd

DEEP, HS, GAP, SEED, N = 0.30, (120, 240), 240, 7, 10000


def yearly(ret_pct):
    """ret_pct: Series of yearly % returns by year. Signal for year t = index >= DEEP below its peak at end of t-1."""
    idx = 100 * (1 + ret_pct / 100).cumprod()
    below = 1 - idx / np.maximum(idx.cummax(), 100.0)  # the 1996 start (100) counts as a high
    return pd.DataFrame({"return_pct": ret_pct, "below_prev_end": below.shift().fillna(0.0)}).assign(
        signal=lambda d: d.below_prev_end >= DEEP)


def perm_p(x, flag, n=N, seed=SEED):
    """Two-sided p for mean(x[flag]) - mean(x[~flag]) by shuffling the labels."""
    x, flag = np.asarray(x, float), np.asarray(flag, bool)
    obs = x[flag].mean() - x[~flag].mean()
    rng = np.random.default_rng(seed)
    null = np.array([(lambda f: x[f].mean() - x[~f].mean())(rng.permutation(flag)) for _ in range(n)])
    return obs, (np.abs(null) >= abs(obs)).mean()


def daily(s):
    below = 1 - s / s.cummax()
    fwd = {h: s.shift(-h) / s - 1 for h in HS}
    sig = below >= DEEP
    rows, ep, last = [], 0, None
    for d in s.index[sig]:
        if last is None or s.index.get_loc(d) - s.index.get_loc(last) > GAP:
            ep += 1
        last = d
        rows.append({"episode": ep, "date": d, "below": below[d], **{f"fwd{h}": fwd[h][d] for h in HS}})
    return pd.DataFrame(rows), {h: fwd[h][~sig].mean() for h in HS}, {h: fwd[h][sig].mean() for h in HS}


if __name__ == "__main__":
    wb = pd.read_csv("results/dse_long_run.csv").set_index("year").return_bdt_pct.dropna()
    Y = yearly(wb)
    diff, p = perm_p(Y.return_pct, Y.signal)
    s = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date").dsex.dropna()
    D, base, on = daily(s)
    Path("results").mkdir(exist_ok=True)
    Y.to_csv("results/deep_low_years.csv", index_label="year")
    D.to_csv("results/deep_low_episodes.csv", index=False)
    sy = Y[Y.signal]
    print(f"A yearly: {len(sy)} signal years {list(sy.index)}; next-year mean {sy.return_pct.mean():+.1f}% vs "
          f"{Y[~Y.signal].return_pct.mean():+.1f}% other years -> diff {diff:+.1f} pts, p {p:.2f}; "
          f"rose in {(sy.return_pct > 0).sum()} of {len(sy)}")
    print(Y.round(2).to_string())
    bd = {h: on[h] - base[h] for h in HS}
    for h in HS:
        print(f"B daily {h} sessions: signal days {100 * on[h]:+.1f}% vs other days {100 * base[h]:+.1f}% -> {100 * bd[h]:+.1f} pts")
    if len(D):
        print(D.groupby("episode").agg(start=("date", "min"), end=("date", "max"), days=("date", "size"),
                                       deepest=("below", "max"), fwd120=("fwd120", "mean"), fwd240=("fwd240", "mean")).round(3).to_string())
    a_up, b_up = diff > 0, all(bd[h] > 0 for h in HS)
    print("Verdict:", "SIGNAL" if a_up and p < 0.05 and b_up else "LEANS UP" if a_up and b_up else "NO")
