"""Brent crude oil price vs the DSEX index. Descriptive: what happened, not a forecast.
Run from the repo root: python scripts/oil_vs_index.py   (--refresh re-downloads Brent from FRED)
Output: results/oil_monthly.csv, results/oil_yearly.csv and a printed summary.
Brent: FRED series DCOILBRENTEU (Europe Brent spot, US$ a barrel, daily), cached in data/raw/fred/.
Brent is in dollars and DSEX in taka; the taka's fall against the dollar (2022-24) is not adjusted for."""
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw/fred/DCOILBRENTEU.csv")
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"


def load_brent(text_path=RAW):
    b = pd.read_csv(text_path, parse_dates=["observation_date"], na_values=".")
    return b.set_index("observation_date").DCOILBRENTEU.dropna().rename("brent")


def monthly(brent, dsex):
    """Month-end Brent and DSEX with their % changes."""
    months = pd.period_range(dsex.index[0], dsex.index[-1], freq="M")  # calendar months, so shift(h) = h months
    M = pd.concat([brent.groupby(brent.index.to_period("M")).last(),
                   dsex.groupby(dsex.index.to_period("M")).last()], axis=1).reindex(months)
    M["brent_chg_pct"] = 100 * M.brent.pct_change()
    M["dsex_chg_pct"] = 100 * M.dsex.pct_change()
    return M


def lead_corr(M, h):
    """Brent % change over the past h months vs DSEX % change over the next h months."""
    past = 100 * (M.brent / M.brent.shift(h) - 1)
    nxt = 100 * (M.dsex.shift(-h) / M.dsex - 1)
    return pd.concat([past, nxt], axis=1).dropna().corr().iloc[0, 1]


if __name__ == "__main__":
    if "--refresh" in sys.argv or not RAW.exists():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=120) as r:
            RAW.write_bytes(r.read())
    brent = load_brent()
    dsex = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date").dsex.dropna()
    brent_all = brent
    brent = brent[brent.index >= dsex.index[0]]

    M = monthly(brent, dsex)
    Y = pd.DataFrame({"brent_avg": brent.groupby(brent.index.year).mean(),
                      "brent_chg_pct": 100 * brent.groupby(brent.index.year).last().pct_change(),
                      "dsex_chg_pct": 100 * dsex.groupby(dsex.index.year).last().pct_change()}).dropna()
    Path("results").mkdir(exist_ok=True)
    M.to_csv("results/oil_monthly.csv", index_label="month")
    Y.to_csv("results/oil_yearly.csv", index_label="year")

    # Daily: DSE closes ~14:30 Dhaka, before Brent's London close, so DSEX on day t only sees Brent closes
    # dated before t (Friday's close lands on Sunday's session).
    seen = pd.Series(brent.values, brent.index + pd.Timedelta(days=1)).reindex(dsex.index, method="ffill")
    dd = pd.concat([np.log(dsex).diff().rename("dsex"), np.log(seen).diff().rename("brent_prev")], axis=1).dropna()
    both = M.dropna()  # months with both changes (Apr-May 2020 DSE closure drops out)
    n = len(both)
    c_m = both.dsex_chg_pct.corr(both.brent_chg_pct)
    by_year = both.groupby(both.index.year).filter(lambda g: len(g) >= 6)  # skip part-years of 1-5 months
    by_year = by_year.groupby(by_year.index.year).apply(lambda g: g.dsex_chg_pct.corr(g.brent_chg_pct))

    # Oil shocks: 3-month Brent move of +/-25% or more; DSEX over the same 3 months and the 3 after.
    r3b = 100 * (M.brent / M.brent.shift(3) - 1)
    r3d = 100 * (M.dsex / M.dsex.shift(3) - 1)
    n3d = 100 * (M.dsex.shift(-3) / M.dsex - 1)
    shocks = pd.DataFrame({"brent_3m": r3b, "dsex_same_3m": r3d, "dsex_next_3m": n3d})
    shocks = shocks[shocks.brent_3m.abs() >= 25]

    pd.set_option("display.width", 200)
    print(Y.round(1).to_string())
    print(f"\n{dsex.index[0]:%b %Y}-{dsex.index[-1]:%b %Y}: DSEX {dsex.iloc[0]:,.0f} -> {dsex.iloc[-1]:,.0f} "
          f"({100 * (dsex.iloc[-1] / dsex.iloc[0] - 1):+.0f}%); Brent ${brent.iloc[0]:.0f} -> ${brent.iloc[-1]:.0f} "
          f"({100 * (brent.iloc[-1] / brent.iloc[0] - 1):+.0f}%)")
    print(f"Level correlation (monthly, misleading for trending series): {both.dsex.corr(both.brent):+.2f}")
    print(f"Monthly % changes, same month, {n} months: correlation {c_m:+.2f} "
          f"(noise band about +/-{2 / np.sqrt(n):.2f})")
    print(f"Daily, DSEX return vs Brent's previous-day return, {len(dd)} days: {dd.dsex.corr(dd.brent_prev):+.3f} "
          f"(noise band about +/-{2 / np.sqrt(len(dd)):.3f})")
    print("Brent change over past 3 / 6 / 12 months vs DSEX over the next 3 / 6 / 12: "
          + " / ".join(f"{lead_corr(M, h):+.2f}" for h in (3, 6, 12))
          + " (overlapping windows: far fewer independent cases than months)")
    print("Same-month correlation by year: " + ", ".join(f"{y} {c:+.2f}" for y, c in by_year.items()))
    print(f"\nMonths ending a 3-month Brent move of 25%+ either way ({len(shocks)}):")
    print(shocks.round(1).to_string())
    sign = np.sign(r3b.where(r3b.abs() >= 25))
    first = shocks[(sign != sign.shift(1)).reindex(shocks.index)]  # first month of each run: overlapping windows
    for name, g in (("up", first[first.brent_3m > 0]), ("down", first[first.brent_3m < 0])):
        print(f"Oil {name} 25%+: {len(g)} episodes, DSEX next 3m median {g.dsex_next_3m.median():+.1f}% "
              f"(over {g.dsex_next_3m.notna().sum()} with a next 3m)")
    print(f"All months: DSEX next 3m median {n3d.median():+.1f}%. With this few episodes a gap under ~6 points "
          "is within what random months give.")
    # shortcut: yearly World Bank taka-per-dollar, latest year held for later years; swap for monthly FX if needed
    fx = pd.read_csv("data/report/dse_world_bank_years.csv").set_index("year").bdt_per_usd.dropna()
    fx0, fx1 = fx.get(dsex.index[0].year, fx.iloc[-1]), fx.get(dsex.index[-1].year, fx.iloc[-1])
    print(f"In one currency (taka {fx0:.0f} -> {fx1:.0f} per $): Brent in taka "
          f"{100 * (brent.iloc[-1] * fx1 / (brent.iloc[0] * fx0) - 1):+.0f}%, DSEX in dollars "
          f"{100 * (dsex.iloc[-1] / fx1 / (dsex.iloc[0] / fx0) - 1):+.0f}%")
    print(f"Latest: Brent ${brent_all.iloc[-1]:.2f} ({brent_all.index[-1]:%d %b %Y}), "
          f"DSEX {dsex.iloc[-1]:,.0f} ({dsex.index[-1]:%d %b %Y})")
