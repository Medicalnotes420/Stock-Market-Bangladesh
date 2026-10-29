"""Market regime (docs/PHASE1_SPEC.md section 3). Every input is a trailing window, so day t uses data <= t.
The macro-calendar blackout is not applied: no event file exists yet."""
import numpy as np
import pandas as pd


def proxy_returns(p, types):
    """Median daily return across equities (gap-flagged rows excluded). Fills days DSEX is missing."""
    eq = [t for t in p.tickers if types.get(t) == "Equity"]
    c = p.close[eq]
    r = (c / c.ffill().shift() - 1).mask(p.gap_flag[eq] | c.isna())
    return r.median(axis=1)


def fill_index(dsex, proxy):
    """DSEX where present; on missing days, chain the proxy return onto the last level."""
    out = dsex.copy()
    for i in range(1, len(out)):
        if np.isnan(out.iloc[i]) and not np.isnan(out.iloc[i - 1]):
            out.iloc[i] = out.iloc[i - 1] * (1 + (proxy.iloc[i] if not np.isnan(proxy.iloc[i]) else 0.0))
    return out


def classify(m, pct_above_50, lock_frac):
    """m: DataFrame[dsex, turnover, adv, dec] by date. Returns RISK_ON / NEUTRAL / RISK_OFF / STRESS."""
    c = m.dsex
    sma100, sma20 = c.rolling(100).mean(), c.rolling(20).mean()
    slope = sma20 - sma20.shift(10)
    bull_t, bear_t = (c > sma100) & (slope > 0), (c < sma100) & (slope < 0)
    vol = c.pct_change().rolling(20).std()
    vol_pct = vol.rolling(250, min_periods=60).apply(lambda w: (w <= w[-1]).mean(), raw=True)
    turn = m.turnover.rolling(20).mean() / m.turnover.rolling(120).mean()
    br = ((m.adv - m.dec) / (m.adv + m.dec)).rolling(10).mean()
    bull_b = (br > 0) & (pct_above_50 > 0.5)
    bear_b = (br < -0.2) & (pct_above_50 < 0.3)
    off = bear_t | bear_b | (vol_pct >= 0.9) | (turn < 0.7)
    on = bull_t & bull_b & (turn >= 1.0) & (vol_pct < 0.8)
    out = np.where(lock_frac > 0.15, "STRESS", np.where(off, "RISK_OFF", np.where(on, "RISK_ON", "NEUTRAL")))
    return pd.Series(out, index=m.index)
