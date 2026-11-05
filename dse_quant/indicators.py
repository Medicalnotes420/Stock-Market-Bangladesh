"""Technical indicators used in the "My Secret Series" rules (docs/SECRETS_LEARNINGS.md).

Each works on a Series or column-wise on a date x ticker panel. Wilder smoothing where the standard
definition uses it. Inputs should be forward-filled closes; every value uses data up to that row only."""
import numpy as np
import pandas as pd


def _wilder(x, n):
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def sma(close, n):
    return close.rolling(n, min_periods=n).mean()


def rsi(close, n=14):
    d = close.diff()
    gain, loss = _wilder(d.clip(lower=0), n), _wilder(-d.clip(upper=0), n)
    return (100 - 100 / (1 + gain / loss)).where(loss > 0, 100.0).where(gain.notna())


def macd(close, fast=12, slow=26, signal=9):
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    return line, line.ewm(span=signal, adjust=False).mean()


def bollinger(close, n=20, k=2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    return upper, mid, lower, (upper - lower) / mid


def aroon_up(high, n=25):
    """100 * (n - sessions since the highest high of the last n+1 sessions) / n."""
    hh = high.rolling(n + 1, min_periods=n + 1).max()
    since = pd.DataFrame(np.nan, high.index, high.columns) if isinstance(high, pd.DataFrame) else pd.Series(np.nan, high.index)
    for k in range(n, -1, -1):  # smallest k wins: the most recent high
        since = since.mask(high.shift(k) >= hh, k)
    return 100 * (n - since) / n


def ema(close, n):
    return close.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(high, low, close, n=14):
    prev = close.shift()
    return _wilder(np.maximum(high - low, np.maximum((high - prev).abs(), (low - prev).abs())), n)


def stoch(high, low, close, n=14, d=3):
    """%K: where the close sits in the n-session high-low range (0-100); %D: its d-session average.
    NaN when the range is zero (no movement)."""
    hh, ll = high.rolling(n, min_periods=n).max(), low.rolling(n, min_periods=n).min()
    k = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    return k, sma(k, d)


def cci(high, low, close, n=14):
    tp = (high + low + close) / 3
    md = tp.rolling(n, min_periods=n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma(tp, n)) / (0.015 * md.replace(0, np.nan))


def adx(high, low, close, n=14):
    up, dn = high.diff(), -low.diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    a = atr(high, low, close, n)
    pdi, mdi = 100 * _wilder(pdm, n) / a, 100 * _wilder(mdm, n) / a
    dx = (100 * (pdi - mdi).abs() / (pdi + mdi)).fillna(0)
    return _wilder(dx, n), pdi, mdi


def mfi(high, low, close, value, n=14):
    """Money Flow Index with DSE traded value as the money flow (it is price x volume already)."""
    tp = (high + low + close) / 3
    pos = value.where(tp > tp.shift(), 0.0).rolling(n, min_periods=n).sum()
    neg = value.where(tp < tp.shift(), 0.0).rolling(n, min_periods=n).sum()
    return (100 - 100 / (1 + pos / neg)).where(neg > 0, 100.0).where(pos.notna())
