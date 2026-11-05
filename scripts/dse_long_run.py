"""DSE yearly picture from 1993: World Bank data (the only free official source this far back; DSE's own archive
pages are gone and the repo's daily DSEX starts Oct 2012). Checked against DSEX where the years overlap.
Run from the repo root: python scripts/dse_long_run.py   (add --refresh to re-download)
Output: results/dse_long_run.csv and a printed table. Raw replies cached in data/raw/worldbank/."""
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsex_history import years  # noqa: E402

RAW = Path("data/raw/worldbank")
URL = "https://api.worldbank.org/v2/country/BGD/indicator/{}?format=json&per_page=100"
SERIES = {"CM.MKT.INDX.ZG": "sp_usd_pct",        # S&P Bangladesh equity index, annual % change, in US dollars
          "PA.NUS.FCRF": "bdt_per_usd",          # official exchange rate, yearly AVERAGE
          "FP.CPI.TOTL.ZG": "inflation_pct",
          "CM.MKT.LCAP.GD.ZS": "mcap_pct_gdp",
          "CM.MKT.TRAD.GD.ZS": "traded_pct_gdp",
          "CM.MKT.TRNR": "turnover_ratio_pct",
          "CM.MKT.LDOM.NO": "listed_companies"}


def fetch(code, refresh=False):
    path = RAW / f"{code}.json"
    if refresh or not path.exists():
        with urllib.request.urlopen(URL.format(code), timeout=60) as r:
            path.write_bytes(r.read())
    d = json.loads(path.read_text())
    if len(d) < 2 or not d[1]:
        raise ValueError(f"World Bank: no data for {code}")
    return pd.Series({int(x["date"]): x["value"] for x in d[1] if x["value"] is not None}, dtype=float)


def build(raw, dsex_years=None):
    t = pd.DataFrame(raw).sort_index()
    t = t[t.index >= 1993]
    # taka return ~ (1 + dollar return) x (taka per dollar, this year / last year) - 1. shortcut: the World Bank
    # rate is a yearly average, not year-end, so this is approximate; checked against DSEX below.
    fx = t.bdt_per_usd / t.bdt_per_usd.shift()
    t["return_bdt_pct"] = ((1 + t.sp_usd_pct / 100) * fx - 1) * 100
    t["real_return_pct"] = ((1 + t.return_bdt_pct / 100) / (1 + t.inflation_pct / 100) - 1) * 100
    if dsex_years is not None:
        t["dsex_return_pct"] = dsex_years.set_index("year")["return"].reindex(t.index) * 100
    return t


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    raw = {name: fetch(code, "--refresh" in sys.argv) for code, name in SERIES.items()}
    m = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date")
    y = years(m[m.dsex.notna()])
    t = build(raw, y[~y.partial])
    Path("results").mkdir(exist_ok=True)
    t.to_csv("results/dse_long_run.csv", index_label="year")
    pd.set_option("display.width", 220)
    print(t.round(1).to_string())
    both = t.dropna(subset=["return_bdt_pct", "dsex_return_pct"])
    print(f"\nCheck vs DSEX, {both.index.min()}-{both.index.max()}: correlation "
          f"{both.return_bdt_pct.corr(both.dsex_return_pct):.2f}, mean gap "
          f"{(both.return_bdt_pct - both.dsex_return_pct).abs().mean():.1f} points")
    r = t.return_bdt_pct.dropna()
    g = (1 + r / 100).prod() ** (1 / len(r)) - 1
    gr = (1 + t.real_return_pct.dropna() / 100).prod() ** (1 / t.real_return_pct.notna().sum()) - 1
    print(f"{r.index.min()}-{r.index.max()} ({len(r)} years): {g:+.1%} a year in taka, {gr:+.1%} after inflation; "
          f"up {int((r > 0).sum())} of {len(r)} years")
