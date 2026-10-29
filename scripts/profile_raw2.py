"""Second-pass diagnostics: A1 date swaps, survivorship in A2, weekend rows, DSEX turnover units."""
import pandas as pd

A1 = "data/raw/a1/DSE_Data.csv"
A2 = "data/raw/a2/x/Dhaka Stock Exchange End-of-Day Financial Dataset/Full Raw Data/"
a1 = pd.read_csv(A1, parse_dates=["Date"]).rename(columns={"Trading_Code": "Ticker"})
raw = pd.read_csv(A2 + "UnAdjusted.csv", parse_dates=["Date"])

dups = a1[a1.duplicated(["Ticker", "Date"], keep=False)].sort_values(["Ticker", "Date"])
print("A1 dup groups identical?", (dups.groupby(["Ticker", "Date"]).Close.nunique() == 1).mean().round(3))

# date-swap test: day<=12 and swapping day/month yields a date that exists in A2 with equal close
a1u = a1.drop_duplicates(["Ticker", "Date"])
m = a1u.merge(raw, on=["Ticker", "Date"], suffixes=("_a1", "_a2"))
bad = m[(m.Close_a1 / m.Close_a2 - 1).abs() > 0.005].copy()
sw = bad[bad.Date.dt.day <= 12].copy()
sw["Swapped"] = pd.to_datetime(dict(year=sw.Date.dt.year, month=sw.Date.dt.day, day=sw.Date.dt.month))
chk = sw.merge(raw.rename(columns={"Date": "Swapped", "Close": "Close_sw"})[["Ticker", "Swapped", "Close_sw"]], on=["Ticker", "Swapped"])
print(f"A1 mismatches={len(bad):,}; with day<=12: {len(sw):,}; of those, match A2 after day/month swap: {((chk.Close_a1/chk.Close_sw-1).abs()<0.005).sum():,}")
print("A1 mismatch rate by year:\n", (m.assign(bad=(m.Close_a1/m.Close_a2-1).abs()>0.005).groupby(m.Date.dt.year).bad.mean().round(3)).to_dict())

# survivorship: A1 tickers alive in 2013-2024 but missing or ending early in A2
a1_last = a1u.groupby("Ticker").Date.agg(["min", "max"])
dead_a1 = a1_last[(a1_last["max"] > "2013-06-01") & (a1_last["max"] < "2024-12-31")]
a2_tk = set(raw.Ticker)
print(f"\nA1 tickers that stopped trading 2013-06..2024: {len(dead_a1)}; present in A2: {sum(t in a2_tk for t in dead_a1.index)}")
print("  examples:", list(dead_a1.index[:25]))
a2_last = raw.groupby("Ticker").Date.max()
print("A2 tickers ending before 2025-06:", a2_last[a2_last < "2025-06-01"].to_dict())

sat = raw[raw.Date.dt.dayofweek == 5]
print("\nA2 Saturday dates:", sorted(sat.Date.dt.date.unique())[:20], "count", sat.Date.nunique())

d = raw[raw.Ticker == "00DSEX"].set_index("Date").Volume
r = d / d.shift(1)
print("\nDSEX 'Volume' jumps >20x or <1/20:", r[(r > 20) | (r < 0.05)].round(1).to_dict())
print("DSEX Volume yearly median (Tk crore):", (d.groupby(d.index.year).median() / 1e7).round(1).to_dict())
