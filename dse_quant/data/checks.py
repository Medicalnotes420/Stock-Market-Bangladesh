"""Data-quality checks. Bad rows are quarantined by the build, never silently fixed."""
import pandas as pd

from dse_quant.limits import TICK_F, limit_pct

INDEX = "00DSEX"


def ohlc_bad(df):
    return ((df.high < df.low) | (df.close > df.high) | (df.close < df.low)
            | (df.open > df.high) | (df.open < df.low) | (df.close <= 0))


def unexplained_gaps(df, actions, slack=0.005):
    """Close-to-close moves beyond the daily limit that no accepted corporate action explains.
    Tolerance is the larger of `slack` and one tick, since limit prices round to the tick on cheap stocks."""
    d = df.sort_values(["ticker", "date"]).copy()
    prev = d.groupby("ticker").close.shift()
    move = (d.close / prev - 1).abs()
    d = d[move > limit_pct(prev) + (TICK_F / prev).clip(lower=slack)]
    known = actions[["ticker", "date"]].assign(date=lambda a: pd.to_datetime(a.date), _a=1)
    d = d.merge(known, on=["ticker", "date"], how="left")
    return d[d._a.isna()].drop(columns="_a").reset_index(drop=True)


def data_status(prices, expected, universe):
    """Inputs for risk.RiskGate: latest bar date, share of universe missing today's bar, index present."""
    expected = pd.Timestamp(expected)
    today = set(prices.loc[prices.date == expected, "ticker"])
    missing = sum(t not in today for t in universe) / len(universe) if len(universe) else 1.0
    return {"latest_bar": prices.date.max().date(), "expected": expected.date(),
            "missing_frac": missing, "has_index": INDEX in today}
