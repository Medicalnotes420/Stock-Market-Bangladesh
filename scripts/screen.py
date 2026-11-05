"""Find DSE shares by their fundamentals, from the newest weekly snapshot (scripts/fundamentals_snapshot.py).
Banks, insurers, NBFIs, mutual funds and bonds are left out unless --financials is given.

  python scripts/screen.py --max-pb 1 --min-yield 0.04 --max-de 1
  python scripts/screen.py --sector Cement                 # every cement share, cheapest Price/NAV first
  python scripts/screen.py --max-pe 15 --top 20

Each share's figures are at its own price on the snapshot day. Lists what matches; not a recommendation."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.fundamentals import eps_stale, latest_snapshot, screen, table  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--max-pe", type=float)
ap.add_argument("--max-pb", type=float, help="Price / NAV")
ap.add_argument("--min-yield", type=float, help="cash dividend yield as a fraction, e.g. 0.04")
ap.add_argument("--max-de", type=float, help="loans / equity")
ap.add_argument("--sector")
ap.add_argument("--financials", action="store_true")
ap.add_argument("--top", type=int, default=30)
a = ap.parse_args()

snap = latest_snapshot()
if not snap:
    sys.exit("no snapshot yet: run python scripts/fundamentals_snapshot.py")
day, records = snap
tab = table(records)
hits = screen(tab, a.max_pe, a.max_pb, a.min_yield, a.max_de, a.sector, a.financials)
print(f"Snapshot {day}: {len(hits)} of {len(tab)} shares match"
      + (f"; showing the first {a.top}" if len(hits) > a.top else ""))
if hits.empty:
    if a.sector and not (tab.sector.str.lower() == a.sector.lower()).any():
        print("no such sector; sectors are:", ", ".join(sorted(tab.sector.dropna().unique())))
    sys.exit(0)
out = hits.head(a.top)[["sector", "category", "price", "eps", "eps_when", "year_end", "pe", "nav", "pb", "div_yield", "debt_equity", "roe"]].copy()
out.insert(5, "stale", ["STALE" if eps_stale(w, y, day) else "" for w, y in zip(out.eps_when, out.year_end)])
out = out.drop(columns="year_end")
for c, fmt in (("pe", "{:.1f}"), ("pb", "{:.2f}"), ("debt_equity", "{:.2f}"), ("div_yield", "{:.1%}"), ("roe", "{:.1%}"),
               ("eps", "{:.2f}"), ("nav", "{:.2f}"), ("price", "{:,.1f}")):
    out[c] = out[c].map(lambda v: "n/a" if v is None or v != v else fmt.format(v))
print(out.to_string())
print("P/E n/a = loss or no EPS. eps_when = the period of that EPS: STALE = that EPS year ended over a year before the snapshot; category Z = DSE's junk board.")
print(f"Each figure is at the share's price on {day}. From dse.com.bd; context, not a recommendation.")
