"""Daily trade plan for a DSE share: stop, target, shares within the hard limits, and the rule's history.

  python scripts/trade_plan.py CROWNCEMNT --equity 200000
  add --entry 56 --stop 52 --target-r 2 --max-loss 1000 --held 15000 to override the defaults

Defaults: entry = last close, stop = 20-session low, target = 2 x risk, max loss = 0.5% of equity.
Reads data/clean/prices.csv.gz (14 years, adjusted). Numbers only, not advice."""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.plan import plan  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("symbol")
ap.add_argument("--equity", type=float, required=True, help="your whole portfolio in Tk")
ap.add_argument("--entry", type=float)
ap.add_argument("--stop", type=float)
ap.add_argument("--target-r", type=float, default=2.0)
ap.add_argument("--max-loss", type=float, help="Tk you accept losing at the stop (default 0.5%% of equity)")
ap.add_argument("--held", type=float, default=0.0, help="Tk you already hold in this share")
a = ap.parse_args()

sym = a.symbol.upper()
df = pd.read_csv("data/clean/prices.csv.gz", usecols=["date", "ticker", "open", "high", "low", "close", "volume",
                                                      "gap_flag"], parse_dates=["date"])
df = df[df.ticker == sym].set_index("date").sort_index()
if len(df) < 60:
    sys.exit(f"{sym}: not enough history in data/clean/prices.csv.gz (check the trading code)")
try:
    p = plan(df, sym, a.equity, a.entry, a.stop, a.target_r, a.max_loss, a.held)
except ValueError as e:
    sys.exit(f"{sym}: {e}")

h = p["history"]
cap = f" (cut from {p['wanted']:,} by {', '.join(p['capped_by'])})" if p["capped_by"] else ""
print(f"{sym} trade plan, data to {p['date']}")
print(f"  entry Tk {p['entry']:,.2f} | stop Tk {p['stop']:,.2f} ({p['risk_pct']:.1%} below) | "
      f"target Tk {p['target']:,.2f} ({a.target_r:g} x risk)")
print(f"  size {p['shares']:,} shares = Tk {p['value']:,.0f}{cap}")
print(f"  at the stop you lose about Tk {p['loss_at_stop']:,.0f} (limit Tk {p['max_loss']:,.0f}); "
      f"at the target you gain about Tk {p['gain_at_target']:,.0f}; costs ~{p['cost_per_side']:.2%} each way extra")
print(f"  same rule on {sym} since {h['from']}, {h['cases']:,} past days, {p['horizon']} sessions each:")
print(f"    target first {h['target_pct']:.0%} | stop first {h['stop_pct']:.0%} | neither {h['open_pct']:.0%} | "
      f"average {h['gross_R']:+.2f} x risk before costs, {h['avg_R']:+.2f} after")
print("  History, not a forecast. A stop can fill lower after a gap or a lower-limit lock. Not investment advice.")
