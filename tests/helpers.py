import pandas as pd


def bars(ticker, closes, start="2020-01-01", volume=100_000):
    """Synthetic daily bars on consecutive business days; OHLC all at close unless edited."""
    dates = pd.bdate_range(start, periods=len(closes))
    df = pd.DataFrame({"date": dates, "ticker": ticker, "close": pd.Series(closes, dtype=float),
                       "volume": float(volume)})
    df["open"] = df["high"] = df["low"] = df["close"]
    df["value"] = df.close * df.volume
    return df[["date", "ticker", "open", "high", "low", "close", "volume", "value"]]
