"""Save every listed share's dse.com.bd company figures as one snapshot (dse_quant.fundamentals). Takes ~5-10
minutes: one page per share, fetched one at a time to go easy on DSE's site.

  python scripts/fundamentals_snapshot.py                 # always
  python scripts/fundamentals_snapshot.py --if-older 6    # only if the newest snapshot is over 6 days old

Writes data/fundamentals/snapshot_<today>.json.gz (git-ignored). Exit code 1 if over 10% of pages failed."""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.fundamentals import latest_snapshot, save_snapshot, trim  # noqa: E402
from dse_quant.watch import company_page, instruments  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--if-older", type=int, help="skip unless the newest snapshot is more than this many days old")
a = ap.parse_args()

last = latest_snapshot()
if a.if_older is not None and last and (date.today() - date.fromisoformat(last[0])).days <= a.if_older:
    print(f"snapshot of {last[0]} is recent enough; skipped")
    sys.exit(0)

inst = instruments()
codes = sorted(inst[inst.category.fillna("").astype(str).str.len() > 0].code)  # indices have no category
records, failed, no_figures = {}, [], []
for i, code in enumerate(codes, 1):
    for attempt in (1, 2):
        try:
            co, items = company_page(code, need_news=False)
            break
        except (OSError, ValueError) as e:
            co, items, err = None, None, e
            time.sleep(3)
    if items is None:
        failed.append(f"{code}: {err}")
    elif co is None:
        no_figures.append(code)  # e.g. bonds and some funds have no company figures
    else:
        records[code] = trim(co, items)
    if i % 50 == 0:
        print(f"{i}/{len(codes)} pages read")
    time.sleep(0.5)

p = save_snapshot(date.today(), records)
print(f"wrote {p}: {len(records)} companies; {len(no_figures)} pages without company figures; {len(failed)} failed")
for f in failed:
    print("FAILED", f, file=sys.stderr)
# a layout change shows up as most pages lacking figures, so check the saved count too
sys.exit(1 if len(failed) > 0.1 * len(codes) or len(records) < 0.7 * len(codes) else 0)
