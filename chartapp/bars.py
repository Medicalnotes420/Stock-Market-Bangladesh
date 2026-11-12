"""Read data/clean/prices.csv.gz as text and hand out Decimal bars (docs/design/eod-chart-app.md 4.1).

pandas is only a string-table reader here: every cell stays `str` until it becomes Decimal, int, bool or date."""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
import re
from functools import cache, lru_cache
from pathlib import Path

import pandas as pd

PRICES = Path(__file__).resolve().parents[1] / "data" / "clean" / "prices.csv.gz"
COLS = ["date", "ticker", "open", "high", "low", "close", "volume", "value", "gap_flag", "close_raw",
        "adj_factor", "lower_lock", "upper_lock", "type"]
_Q4 = Decimal("0.0001")
_BOOL = {"True": True, "False": False}
_PLAIN = re.compile(r"[0-9]+(\.[0-9]+)?")


@dataclass(frozen=True, slots=True)
class Bar:
    """What pattern plugins and geometry get. Prices are back-adjusted."""
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class Row(Bar):
    """API and labels only: adj_factor and the flags depend on later bars, so plugins must not see them."""
    value: Decimal
    close_raw: Decimal
    adj_factor: Decimal
    gap_flag: bool
    lower_lock: bool
    upper_lock: bool


def _plain(text: str) -> Decimal:
    # plain digits only: no sign, exponent, nan, spaces or underscores, so str() of the result is plain too
    if not _PLAIN.fullmatch(text):
        raise ValueError(f"not a plain non-negative decimal: {text!r}")
    return Decimal(text)


def dec(text: str) -> Decimal:
    """CSV text to Decimal with no float step. The file was written from floats, so values with float
    noise (7.573440000000005) are cut to 4 dp; tick prices (56.2) pass through unchanged."""
    d = _plain(text)
    return d if d.as_tuple().exponent >= -4 else d.quantize(_Q4, rounding=ROUND_HALF_EVEN)


def whole(text: str) -> int:
    """Share count: stored as "3163.0"."""
    d = _plain(text)
    if d != d.to_integral_value():
        raise ValueError(f"not a whole number: {text!r}")
    return int(d)


@cache
def _table(path: Path) -> dict[str, pd.DataFrame]:
    # na_filter=False: an empty cell stays "" instead of becoming NaN, which is a float
    df = pd.read_csv(path, dtype=str, na_filter=False, usecols=COLS)
    return {t: g for t, g in df.groupby("ticker", sort=False)}


def table(path: Path = PRICES) -> dict[str, pd.DataFrame]:
    """Whole file as strings, split by ticker. Read once per path; restart after a rebuild.
    shortcut: whole file in memory, about 9 s at startup; split per ticker in a build step if that hurts."""
    return _table(path)  # the cache sits on _table so table() and table(PRICES) share one entry


def rows(ticker: str, path: Path = PRICES) -> tuple[Row, ...]:
    """All rows of one ticker, oldest first. KeyError for an unknown ticker."""
    return _rows(ticker, path)


@lru_cache(maxsize=64)  # bounded: all 533 tickers as Rows would be about 1.2M objects
def _rows(ticker: str, path: Path) -> tuple[Row, ...]:
    out = tuple(
        Row(date.fromisoformat(r.date), dec(r.open), dec(r.high), dec(r.low), dec(r.close), whole(r.volume),
            dec(r.value), dec(r.close_raw), dec(r.adj_factor), _BOOL[r.gap_flag], _BOOL[r.lower_lock],
            _BOOL[r.upper_lock])
        for r in table(path)[ticker].itertuples(index=False))
    if any(a.date >= b.date for a, b in zip(out, out[1:])):
        raise ValueError(f"{ticker}: dates are not strictly increasing")
    return out


def bars(rs: tuple[Row, ...]) -> tuple[Bar, ...]:
    """Strip rows to the plugin view."""
    return tuple(Bar(r.date, r.open, r.high, r.low, r.close, r.volume) for r in rs)
