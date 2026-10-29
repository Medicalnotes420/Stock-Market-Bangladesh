"""Performance metrics. Deflated Sharpe follows Bailey & Lopez de Prado (2014)."""
import math
from statistics import NormalDist

import pandas as pd

PPY = 240  # DSE sessions per year (approx.)
_N = NormalDist()


def sharpe(r):
    r = pd.Series(r).dropna()
    sd = r.std()
    return 0.0 if len(r) < 2 or not sd > 0 else float(r.mean() / sd * math.sqrt(PPY))


def max_drawdown(equity):
    e = pd.Series(equity).dropna()
    return float((1 - e / e.cummax()).max())


def trade_stats(pnl):
    pnl = pd.Series(pnl).dropna()
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return {"trades": int(len(pnl)), "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
            "profit_factor": float(wins / losses) if losses > 0 else math.inf}


def deflated_sharpe(r, n_trials, sr_var):
    """P(true Sharpe > best-of-n_trials-by-luck). sr_var: variance of per-period Sharpe across all trials."""
    r = pd.Series(r).dropna()
    t, sd = len(r), r.std()
    if t < 3 or not sd > 0:
        return 0.0
    sr = r.mean() / sd
    if n_trials <= 1 or sr_var <= 0:
        sr0 = 0.0
    else:
        g = 0.5772156649
        sr0 = math.sqrt(sr_var) * ((1 - g) * _N.inv_cdf(1 - 1 / n_trials)
                                   + g * _N.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = math.sqrt(max(1e-12, 1 - r.skew() * sr + (r.kurt() + 2) / 4 * sr ** 2))  # kurt() is excess
    return _N.cdf((sr - sr0) * math.sqrt(t - 1) / den)
