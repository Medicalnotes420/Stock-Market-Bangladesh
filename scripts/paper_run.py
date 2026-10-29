"""Daily paper run. Run from the repo root after the DSE close:
  python scripts/paper_run.py                  # as of today
  python scripts/paper_run.py --asof 2026-01-22
  python scripts/paper_run.py --replay 10      # last 10 sessions, oldest first (needs a fresh data/paper/)
State, journal and order files go to data/paper/ (git-ignored). Prints the monitoring summary."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.data.load import load_a2_types  # noqa: E402
from dse_quant.paper.harness import daily_run  # noqa: E402
from dse_quant.paper.monitor import summarize  # noqa: E402

OUT = Path("data/paper")
ap = argparse.ArgumentParser()
ap.add_argument("--asof", default=str(date.today()))
ap.add_argument("--replay", type=int, default=0)
a = ap.parse_args()

prices = pd.read_csv("data/clean/prices.csv.gz", parse_dates=["date"])
market = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date")
types = {**json.load(open("data/clean/report.json"))["dead_tickers_from_a1"], **load_a2_types()}
days = sorted(prices.date.unique())[-a.replay:] if a.replay else [pd.Timestamp(a.asof)]
paths = dict(state_path=OUT / "state.json", journal_path=OUT / "journal.jsonl", orders_dir=OUT / "orders")
for d in days:
    e = daily_run(prices, market, types, d, **paths)
    print(e["asof"], "regime", e["regime"], "gate", "OPEN" if e["gate_open"] else f"CLOSED {e['gate_reasons']}",
          "orders", len(e["orders"]), "alerts", e["alerts"])
print(json.dumps(summarize(paths["journal_path"]), indent=1))
