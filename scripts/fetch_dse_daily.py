"""Bring data/raw/dse/ up to yesterday from stocknow.com.bd, for every listed share, so build_clean.py has
full-market days again (breadth, turnover, regime). Run from the repo root:
  python scripts/fetch_dse_daily.py

Writes (all git-ignored, read by dse_quant.data.load):
  data/raw/dse/dayend_stocknow_<start>_<end>.csv   unadjusted daily bars, every share, the missing days only
  data/raw/dse/market_summary_stocknow_<date>.csv  DSEX close + total traded value of the latest session
stocknow's export has no traded value or trade count: value_mn is close x volume and trades is 1 on traded days
(shortcut: approximations; switch to DSE's own figures if a source with them appears). Its export also has no
DSEX history, so DSEX is saved only for the latest session; build_clean chains missed days from the median share
return (dse_quant.regime.fill_index). Exit code 1 on any failure; files already written are kept."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.data.load import DSE_DIR, load_dse_market  # noqa: E402
from dse_quant.watch import export_rows, instruments  # noqa: E402

FIRST = date(2026, 1, 23)  # day after the A2 dataset ends; earlier days are already in data/clean
CHUNK_DAYS = 31            # keeps each reply to ~15k rows

DSE_DIR.mkdir(parents=True, exist_ok=True)
done = [pd.read_csv(f, usecols=["date"]).date.max() for f in DSE_DIR.glob("dayend_stocknow_*.csv")]
start = max([FIRST] + [date.fromisoformat(d) + timedelta(days=1) for d in done])
end = date.today() - timedelta(days=1)  # stocknow only exports finished days

inst = instruments()
shares = inst[inst.category.fillna("").astype(str).str.len() > 0]  # indices (DSEX, DS30, DSES) have no category
print(f"{len(shares)} shares; fetching {start} to {end}")

if start <= end:
    parts, s = [], start
    while s <= end:
        e = min(s + timedelta(days=CHUNK_DAYS - 1), end)
        parts.append(export_rows(shares.code.tolist(), s, e, adjusted=False))
        s = e + timedelta(days=1)
    d = pd.concat(parts, ignore_index=True)
    if len(d):
        for c in ["open", "high", "low", "close", "volume"]:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        bad = d[["date", "open", "high", "low", "close", "volume"]].isna().any(axis=1)
        if bad.any():
            print(f"dropped {int(bad.sum())} rows with missing or non-numeric values", file=sys.stderr)
        d = d[~bad & (d.volume > 0)]
        out = pd.DataFrame({"date": d.date, "ticker": d.symbol, "open": d.open, "high": d.high, "low": d.low,
                            "close": d.close, "trades": 1, "value_mn": d.close * d.volume / 1e6, "volume": d.volume})
        f = DSE_DIR / f"dayend_stocknow_{out.date.min()}_{out.date.max()}.csv"
        out.sort_values(["date", "ticker"]).to_csv(f, index=False)
        print(f"wrote {f} ({len(out)} rows, {out.date.nunique()} sessions)")
    else:
        print("no new sessions (holidays or weekend)")

dsex = inst[inst.code == "DSEX"]
if dsex.empty:
    sys.exit("stocknow: DSEX missing from the instrument list")
r = dsex.iloc[0]
day = str(r.updated_at)[:10]
if pd.Timestamp(day) not in load_dse_market().index:
    f = DSE_DIR / f"market_summary_stocknow_{day}.csv"
    pd.DataFrame({"date": [day], "dsex": [float(r.close)], "total_value_mn": [float(r.value)]}).to_csv(f, index=False)
    print(f"wrote {f} (DSEX {float(r.close):,.2f})")
