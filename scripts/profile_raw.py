"""One-off profile of the two raw Mendeley datasets. Prints facts used in docs/PHASE3_DATA.md."""
import pandas as pd

A1 = "data/raw/a1/DSE_Data.csv"
A2 = "data/raw/a2/x/Dhaka Stock Exchange End-of-Day Financial Dataset/Full Raw Data/"

a1 = pd.read_csv(A1, parse_dates=["Date"]).rename(columns={"Trading_Code": "Ticker"})
raw = pd.read_csv(A2 + "UnAdjusted.csv", parse_dates=["Date"])
adj = pd.read_csv(A2 + "Adjusted.csv", parse_dates=["Date"])

for name, d in [("A1", a1), ("A2raw", raw), ("A2adj", adj)]:
    print(f"\n== {name}: rows={len(d):,} tickers={d.Ticker.nunique()} dates={d.Date.min().date()}..{d.Date.max().date()} days={d.Date.nunique()}")
    print("  dup (Ticker,Date):", d.duplicated(["Ticker", "Date"]).sum())
    print("  nulls:", d.isna().sum().to_dict())
    print("  weekday counts:", d.Date.dt.day_name().value_counts().to_dict())
    bad = d[(d.High < d.Low) | (d.Close > d.High) | (d.Close < d.Low) | (d.Close <= 0)]
    print("  OHLC violations:", len(bad))
    last = d.groupby("Ticker").Date.max()
    print("  tickers whose last date < 1y before dataset end (dead?):", (last < d.Date.max() - pd.Timedelta(days=365)).sum())

print("\nA2 tickers starting 00:", sorted(t for t in raw.Ticker.unique() if t.startswith("00")))
print("A1 index-like tickers:", sorted(t for t in a1.Ticker.unique() if "DSE" in t.upper() or t.startswith("00")))

# overlap check A1 vs A2 raw close
m = a1.merge(raw, on=["Ticker", "Date"], suffixes=("_a1", "_a2"))
rel = (m.Close_a1 / m.Close_a2 - 1).abs()
print(f"\nA1 vs A2raw overlap rows={len(m):,}; close |diff|>0.5%: {(rel > 0.005).sum():,} ({(rel > 0.005).mean():.2%}); vol mismatch: {(m.Volume_a1 != m.Volume_a2).mean():.2%}")
print("worst examples:\n", m.assign(rel=rel).nlargest(5, "rel")[["Ticker", "Date", "Close_a1", "Close_a2"]])

# daily returns beyond 10.5% in raw A2 (circuit max 10%) -> corporate actions or errors
raw = raw.sort_values(["Ticker", "Date"])
raw["ret"] = raw.groupby("Ticker").Close.pct_change()
stocks = raw[~raw.Ticker.str.startswith("00")]
big = stocks[stocks.ret.abs() > 0.105]
print(f"\nA2raw stock-days |ret|>10.5%: {len(big):,} of {stocks.ret.notna().sum():,}; down: {(big.ret<0).sum():,} up: {(big.ret>0).sum():,}")

# implied adjustment factor adj/raw changes
f = raw.merge(adj, on=["Ticker", "Date"], suffixes=("", "_adj"))
f = f[~f.Ticker.str.startswith("00")]
f["factor"] = f.Close_adj / f.Close
f["fchg"] = f.groupby("Ticker").factor.pct_change().abs()
print("A2 implied adjustment events (factor change >0.1%):", (f.fchg > 0.001).sum(), "tickers with any:", f[f.fchg > 0.001].Ticker.nunique())
big2 = big.merge(f[["Ticker", "Date", "fchg"]], on=["Ticker", "Date"], how="left")
print("  of big down-moves, explained by an A2 factor change:", ((big2.ret < 0) & (big2.fchg > 0.001)).sum(), "/", (big2.ret < 0).sum())

dsex = raw[raw.Ticker == "00DSEX"]
print("\nDSEX raw:", dsex.Date.min().date(), dsex.Date.max().date(), len(dsex), "rows; sample vol", dsex.Volume.tail(3).tolist())
dsexa = adj[adj.Ticker == "00DSEX"]
print("DSEX adj vol/raw vol ratio:", (dsexa.Volume.values[:5] / dsex.Volume.values[:5]).round(2))
