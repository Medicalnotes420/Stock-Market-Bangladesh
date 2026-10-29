"""DSE daily price limits (circuit breakers) and limit-lock detection. Tiers: docs/PHASE1_SPEC.md section 1."""
import numpy as np
import pandas as pd

# shortcut: one tick size for all prices; confirm the DSE tick table before trusting fills near the limit
TICK = 0.10
_BINS = [0, 200, 500, 1000, 2000, 5000, np.inf]
_PCTS = [0.10, 0.0875, 0.075, 0.0625, 0.05, 0.0375]


def limit_pct(prev_close: pd.Series) -> pd.Series:
    """Max daily move as a fraction of the previous close (upper bound of each tier inclusive)."""
    return pd.cut(prev_close, _BINS, right=True, labels=_PCTS).astype(float)


def lock_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Add prev_close, limit, lower_lock, upper_lock. A close within one tick of the limit counts as locked:
    the backtest assumes no sell fill on a lower-lock day and no buy fill on an upper-lock day."""
    out = df.sort_values(["ticker", "date"]).copy()
    out["prev_close"] = out.groupby("ticker").close.shift()
    out["limit"] = limit_pct(out.prev_close)
    eps = 1e-9
    out["lower_lock"] = out.close <= out.prev_close * (1 - out.limit) + TICK + eps
    out["upper_lock"] = out.close >= out.prev_close * (1 + out.limit) - TICK - eps
    return out
