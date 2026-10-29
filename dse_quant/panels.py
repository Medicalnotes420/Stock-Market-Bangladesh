"""Wide (date x ticker) panels from the clean long table, plus a vectorised universe mask.

eligible_mask must give the same answer as universe.eligible (tested); it exists because calling
eligible() for each of ~3,000 dates is too slow for parameter sweeps."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from dse_quant.universe import UniverseRules


@dataclass
class Panels:
    dates: pd.DatetimeIndex
    tickers: list
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    close_raw: pd.DataFrame
    value: pd.DataFrame
    lower_lock: pd.DataFrame
    upper_lock: pd.DataFrame
    gap_flag: pd.DataFrame
    atr: pd.DataFrame       # ATR(20) on adjusted prices, known at that day's close
    adtv: pd.DataFrame      # mean traded value over 20 sessions, no-trade days count as 0
    vol: pd.DataFrame       # std of daily returns over 20 sessions (for impact cost)


def build_panels(df):
    piv = lambda c: df.pivot(index="date", columns="ticker", values=c).sort_index()
    close = piv("close")
    high, low = piv("high"), piv("low")
    prev = close.ffill().shift()
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()]).groupby(level=0).max()
    tr = tr.where(close.notna())
    value = piv("value")
    flag = lambda c: piv(c).astype("boolean").fillna(False).astype(bool)
    return Panels(
        dates=close.index, tickers=list(close.columns), open=piv("open"), high=high, low=low,
        close=close, close_raw=piv("close_raw"), value=value,
        lower_lock=flag("lower_lock"), upper_lock=flag("upper_lock"), gap_flag=flag("gap_flag"),
        atr=tr.rolling(20, min_periods=15).mean(),
        adtv=value.fillna(0).rolling(20, min_periods=20).mean(),
        vol=close.pct_change(fill_method=None).rolling(20, min_periods=15).std())


def eligible_mask(p, types, rules=UniverseRules()):
    has = p.close.notna()
    n = has.rolling(rules.lookback, min_periods=rules.lookback).sum()
    med = p.value.rolling(rules.lookback, min_periods=1).median()
    hist = has.cumsum()
    locked = p.lower_lock.astype(float).rolling(rules.no_lower_lock_days, min_periods=1).max() > 0
    eq = pd.Series([types.get(t) == "Equity" for t in p.tickers], index=p.tickers)
    m = (has & (n >= rules.min_trade_frac * rules.lookback) & (med >= rules.min_median_value)
         & (hist >= rules.min_history) & (p.close_raw >= rules.min_price) & ~locked)
    return m & eq.values[np.newaxis, :]
