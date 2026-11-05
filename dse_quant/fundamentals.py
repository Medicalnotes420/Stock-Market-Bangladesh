"""Weekly snapshot of every DSE company page, and what it allows: sector comparison and a screener.

A snapshot is data/fundamentals/snapshot_<date>.json.gz = {"day": date, "records": {code: company record}}, each
record trimmed to what watch.fundamentals() reads plus its dividend news. Kept forever, so fundamentals can be
tested against later prices once enough weeks pile up (DSE keeps no past snapshots)."""
import gzip
import json
from pathlib import Path

import pandas as pd

from dse_quant.watch import fundamentals

SNAP_DIR = Path("data/fundamentals")
KEEP = ("code", "name", "sector", "category", "board", "price", "marketCap", "faceValue", "paidUpCapital",
        "freeFloat", "authorizedCapital", "reserveWithoutOci", "loanStatus", "listingYear", "yearEnd", "agmDate",
        "asOfDate", "multiYearFinancials", "interimFinancials", "dividendHistory", "sharePattern")
# sectors the user does not follow; the screener leaves them out unless asked
FINANCIAL = ("Bank", "Financial Institutions", "Insurance", "Mutual Funds", "Corporate Bond", "Treasury Bond")
METRICS = {"pe": True, "pb": True, "div_yield": False, "roe": False, "debt_equity": True}  # True: lower ranks first


def trim(company, news):
    """The parts of a parse_company record and its news that fundamentals() needs."""
    rec = {k: company.get(k) for k in KEEP}
    rec["news"] = [x for x in news if x.get("type") == "Dividend"]
    return rec


def save_snapshot(day, records, folder=SNAP_DIR):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"snapshot_{day}.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump({"day": str(day), "records": records}, f)
    return p


def latest_snapshot(folder=SNAP_DIR):
    """(day, records) of the newest snapshot, or None."""
    files = sorted(Path(folder).glob("snapshot_*.json.gz"))
    if not files:
        return None
    with gzip.open(files[-1], "rt", encoding="utf-8") as f:
        s = json.load(f)
    return s["day"], s["records"]


def table(records):
    """One row per share: sector, price and the fundamentals() figures at each record's own price."""
    rows = []
    for code, r in records.items():
        price = r.get("price")
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        try:
            f = fundamentals(r, float(price), r.get("news") or [])
        except Exception:  # one odd record must not sink the table
            continue
        rows.append({"code": code, "sector": r.get("sector"), "category": r.get("category"), "price": float(price),
                     "market_cap_mn": f["market_cap_mn"], "eps": f["eps"], "nav": f["nav"],
                     **{k: f[k] for k in METRICS}, "div_cash_pct": f["div_cash_pct"]})
    return pd.DataFrame(rows).set_index("code") if rows else pd.DataFrame()


def sector_view(tab, code, day):
    """This share against its sector in a table(): per metric its value, the sector median, its rank and how many
    peers have the figure. A str explaining why when it can't."""
    if tab.empty or code not in tab.index:
        return f"{code} is not in the {day} snapshot"
    sec = tab.loc[code, "sector"]
    peers = tab[tab.sector == sec]
    if len(peers) < 3:
        return f"only {len(peers)} share(s) in the {sec} sector in the {day} snapshot"
    out = {}
    for k, low_first in METRICS.items():
        col = peers[k].astype(float)
        if k == "pe":
            col = col.where(col > 0)
        have = col.dropna()
        v = col.get(code)
        rank = int((have < v).sum() + 1) if low_first else int((have > v).sum() + 1)
        out[k] = {"share": None if pd.isna(v) else float(v), "median": float(have.median()) if len(have) else None,
                  "rank": None if pd.isna(v) else rank, "n": int(len(have))}
    return {"sector": sec, "members": int(len(peers)), "day": day, "metrics": out}


def screen(tab, max_pe=None, max_pb=None, min_yield=None, max_de=None, sector=None, financials=False):
    """Shares passing every given limit, cheapest Price/NAV first. A missing figure fails a limit set on it."""
    t = tab if financials else tab[~tab.sector.isin(FINANCIAL)]
    if sector:
        t = t[t.sector.str.lower() == sector.lower()]
    for col, lim, keep in (("pe", max_pe, lambda c, x: (c > 0) & (c <= x)), ("pb", max_pb, lambda c, x: c <= x),
                           ("div_yield", min_yield, lambda c, x: c >= x), ("debt_equity", max_de, lambda c, x: c <= x)):
        if lim is not None:
            c = t[col].astype(float)
            t = t[keep(c, lim).fillna(False) & c.notna()]
    return t.sort_values("pb", na_position="last")
