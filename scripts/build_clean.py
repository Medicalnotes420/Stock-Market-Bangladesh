"""Build data/clean/ from the raw Mendeley files. Run from the repo root: python scripts/build_clean.py"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.data.adjust import apply_actions, infer_actions  # noqa: E402
from dse_quant.data.checks import INDEX, ohlc_bad, unexplained_gaps  # noqa: E402
from dse_quant.data.load import load_a1, load_a2, load_a2_types, repair_a1_dates  # noqa: E402
from dse_quant.limits import lock_flags  # noqa: E402
from dse_quant.universe import eligible  # noqa: E402

OUT = Path("data/clean")
# shortcut: A1-only (dead) tickers have no type metadata; name pattern guess, listed in report for review
NON_EQUITY = re.compile(r"BOND|SUKUK|MF$|1STMF|NRB|ICB.*1ST|GRAMEEN|^TB\d|^DS(EX|ES|30)$|^00|GF$")

rep = {}
raw, adj, types = load_a2("UnAdjusted"), load_a2("Adjusted"), load_a2_types()
a1, rep["a1_repair"] = repair_a1_dates(load_a1(), raw)

m = a1.merge(raw, on=["ticker", "date"], suffixes=("", "_a2"))
rep["a1_vs_a2_after_repair"] = {"overlap_rows": len(m),
                                "close_diff_gt_0.5pct": round(float(((m.close / m.close_a2 - 1).abs() > .005).mean()), 4)}

dead = a1[~a1.ticker.isin(set(raw.ticker))]
dead_types = {t: ("Unknown" if NON_EQUITY.search(t) else "Equity") for t in sorted(dead.ticker.unique())}
rep["dead_tickers_from_a1"] = dead_types
types = {**dead_types, **types}
prices = pd.concat([raw.assign(source="a2"), dead.assign(source="a1")], ignore_index=True)

bad = ohlc_bad(prices)
rep["quarantined_ohlc_rows"] = int(bad.sum())
quarantine = prices[bad].assign(reason="ohlc")
prices = prices[~bad]

actions = infer_actions(raw, adj)
gaps = unexplained_gaps(prices[prices.ticker != INDEX], actions)
rep["actions_accepted"] = len(actions)
rep["unexplained_gaps"] = len(gaps)
rep["unexplained_gaps_tickers"] = int(gaps.ticker.nunique())
quarantine = pd.concat([quarantine, gaps[prices.columns].assign(reason="gap_no_action")])
prices = prices.merge(gaps[["ticker", "date"]].assign(gap_flag=True), on=["ticker", "date"], how="left")
prices["gap_flag"] = prices.gap_flag.fillna(False).astype(bool)

clean = lock_flags(apply_actions(prices, actions))
clean["type"] = clean.ticker.map(types).fillna("Unknown")

eq = clean[clean.type == "Equity"].copy()
eq["ret"] = eq.close / eq.groupby("ticker").close.shift() - 1
market = pd.DataFrame({
    "dsex": clean[clean.ticker == INDEX].set_index("date").close,
    "turnover": eq.groupby("date").value.sum(),
    "adv": eq[eq.ret > 0].groupby("date").size(),
    "dec": eq[eq.ret < 0].groupby("date").size(),
    "n": eq.groupby("date").size(),
}).fillna({"adv": 0, "dec": 0}).sort_index()

years = {}
for y, d in market.groupby(market.index.year).tail(1).index.to_series().items():
    years[str(d.date())] = len(eligible(clean, d, types))
rep["universe_size_year_end"] = years
rep["rows"], rep["tickers"] = len(clean), int(clean.ticker.nunique())
rep["dates"] = [str(clean.date.min().date()), str(clean.date.max().date())]
rep["dsex_rows"], rep["dsex_missing_days"] = int(market.dsex.notna().sum()), int(market.dsex.isna().sum())

OUT.mkdir(parents=True, exist_ok=True)
clean.to_csv(OUT / "prices.csv.gz", index=False)
actions.to_csv(OUT / "actions.csv", index=False)
quarantine.to_csv(OUT / "quarantine.csv", index=False)
market.to_csv(OUT / "market.csv", index_label="date")
(OUT / "report.json").write_text(json.dumps(rep, indent=1, default=str))
print(json.dumps({k: v for k, v in rep.items() if k != "dead_tickers_from_a1"}, indent=1, default=str))
print("dead tickers:", len(dead_types), "equity-guess:", sum(v == "Equity" for v in dead_types.values()))
