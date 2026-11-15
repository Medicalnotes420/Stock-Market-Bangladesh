"""Load the two Mendeley datasets (docs/PHASE3_DATA.md) into one long format:
date, ticker, open, high, low, close, volume, value. Raw files are read, never written."""
from pathlib import Path

import pandas as pd

COLS = ["date", "ticker", "open", "high", "low", "close", "volume", "value"]
A1_FILE = Path("data/raw/a1/DSE_Data.csv")
A2_DIR = Path("data/raw/a2/x/Dhaka Stock Exchange End-of-Day Financial Dataset")
DSE_DIR = Path("data/raw/dse")


def _norm(df):
    df = df.rename(columns=str.lower).rename(columns={"trading_code": "ticker"})
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str).str.strip()
    df["value"] = df.close * df.volume  # traded value approximation, raw (unadjusted) prices
    return df[COLS]


def load_a2(kind="UnAdjusted", root=A2_DIR):
    return _norm(pd.read_csv(root / "Full Raw Data" / f"{kind}.csv"))


def load_a2_types(root=A2_DIR):
    md = pd.read_csv(root / "metadata" / "company_metadata.csv")
    return dict(zip(md.Ticker.str.strip(), md.Instrument_Type))


def load_dse_prices(root=DSE_DIR):
    """Day-end rows copied from dse.com.bd/data-archives (personal use). value_mn is DSE's traded value."""
    files = sorted(Path(root).glob("dayend_*.csv"))
    if not files:
        return pd.DataFrame(columns=COLS)
    d = pd.concat(map(pd.read_csv, files)).drop_duplicates()
    d = d[d.trades > 0]  # no-trade days: DSE repeats yesterday's close with zero volume, not a bar
    d = d.assign(date=pd.to_datetime(d.date), ticker=d.ticker.str.strip(), value=d.value_mn * 1e6)
    return d[COLS].drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"]).reset_index(drop=True)


def load_dse_market(root=DSE_DIR):
    """DSE market summary: DSEX and total traded value. No breadth, so adv/dec/n are unknown (NaN)."""
    files = sorted(Path(root).glob("market_summary_*.csv"))
    if not files:
        return pd.DataFrame(columns=["dsex", "turnover", "adv", "dec", "n"])
    d = pd.concat(map(pd.read_csv, files)).drop_duplicates("date")
    d = d.assign(date=pd.to_datetime(d.date), turnover=d.total_value_mn * 1e6, adv=float("nan"),
                 dec=float("nan"), n=float("nan"))
    return d.set_index("date").sort_index()[["dsex", "turnover", "adv", "dec", "n"]]


def load_a1(path=A1_FILE):
    return _norm(pd.read_csv(path))


def repair_a1_dates(a1, ref, tol=0.005):
    """A1 was published with day/month swapped on many dates (whole-date blocks). For every A1 date that is
    ambiguous (day <= 12, day != month), vote across tickers present in `ref` on whether the A1 closes match
    ref at the parsed date or at the swapped date; move the whole block to the winner. Unresolvable dates and
    rows before ref starts are dropped, since nothing can verify them."""
    a1 = a1.assign(ticker=a1.ticker.str.strip()).drop_duplicates()
    rep = {"rows_in": len(a1)}
    key = ["ticker", "date"]
    conflict = a1.duplicated(key, keep=False)
    rep["conflicting_dups"] = int(a1[conflict].drop_duplicates(key).shape[0])
    a1 = a1[~conflict]

    pre = a1.date < ref.date.min()
    rep["dropped_pre_ref"] = int(pre.sum())
    a1 = a1[~pre]

    d = a1.date
    ambiguous = (d.dt.day <= 12) & (d.dt.day != d.dt.month)
    swapped = pd.to_datetime(dict(year=d.dt.year, month=d.dt.day.where(ambiguous, d.dt.month),
                                  day=d.dt.month.where(ambiguous, d.dt.day)))
    a1 = a1.assign(swapped=swapped, ambiguous=ambiguous)

    r = ref[key + ["close"]].rename(columns={"close": "ref_close"})
    amb = a1[a1.ambiguous]
    as_is = amb.merge(r, on=key)
    as_sw = amb.merge(r.rename(columns={"date": "swapped"}), on=["ticker", "swapped"])
    votes = pd.DataFrame({
        "keep": as_is.assign(ok=(as_is.close / as_is.ref_close - 1).abs() <= tol).groupby("date").ok.sum(),
        "swap": as_sw.assign(ok=(as_sw.close / as_sw.ref_close - 1).abs() <= tol).groupby("date").ok.sum(),
    }).fillna(0)
    to_swap = set(votes.index[votes.swap > votes.keep])
    resolved = set(votes.index[votes.swap != votes.keep])
    rep["swapped_dates"] = len(to_swap)

    drop = a1.ambiguous & ~a1.date.isin(resolved)
    rep["dropped_unresolved_rows"] = int(drop.sum())
    a1 = a1[~drop]
    a1 = a1.assign(date=a1.swapped.where(a1.date.isin(to_swap), a1.date))
    again = a1.duplicated(key, keep=False)
    rep["dropped_post_repair_dups"] = int(again.sum())
    out = a1[~again][COLS].sort_values(key).reset_index(drop=True)
    rep["rows_out"] = len(out)
    return out, rep
