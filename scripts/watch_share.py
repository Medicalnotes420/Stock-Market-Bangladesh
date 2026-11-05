"""Watch how DSE shares are moving. Writes data/watch/watch.html (git-ignored).

  python scripts/watch_share.py                       # shares in watchlist.txt, fresh from stocknow
  python scripts/watch_share.py --symbols ACI GP      # named shares, fresh from stocknow
  python scripts/watch_share.py --csv my_share.csv    # an uploaded daily OHLCV file instead
  add --above 180 --below 170 for price-level alerts (applied to every share shown)

Fetched bars are saved as data/watch/<SYMBOL>.csv. Exit code 1 if any share failed."""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.watch import (adjust_for_dividend, analyze, company_page, fetch, fundamentals,  # noqa: E402
                             latest_regime, load_csv, log_forecasts, rates_status, render, score_forecasts)

OUT = Path("data/watch")
HISTORY_DAYS = 400  # calendar days: ~270 sessions, enough for SMA50 and a 250-session chart

ap = argparse.ArgumentParser()
ap.add_argument("--csv", nargs="+", help="uploaded CSV file(s), one share each")
ap.add_argument("--symbols", nargs="+", help="DSE trading codes to fetch (default: watchlist.txt)")
ap.add_argument("--above", type=float)
ap.add_argument("--below", type=float)
ap.add_argument("--out", default=str(OUT / "watch.html"))
a = ap.parse_args()

data, errors = {}, []
if a.csv:
    for f in a.csv:
        try:
            data[Path(f).stem.upper()] = load_csv(f)
        except (ValueError, OSError) as e:
            errors.append(str(e))
    note = "Source: uploaded file(s) " + ", ".join(Path(f).name for f in a.csv)
else:
    wl = Path("watchlist.txt")
    syms = [s.upper() for s in a.symbols] if a.symbols else [
        l.strip().upper() for l in wl.read_text().splitlines() if l.strip() and not l.startswith("#")] if wl.exists() else []
    if not syms:
        sys.exit("no shares: pass --symbols or add trading codes to watchlist.txt")
    # adjusted prices so splits/bonus shares do not show as crashes; refetched in full each run because
    # adjustments rewrite history
    end = date.today() - timedelta(days=1)  # the site only exports finished days anyway
    try:
        data = fetch(syms, end - timedelta(days=HISTORY_DAYS), end, adjusted=True)
    except (OSError, ValueError) as e:
        errors.append(f"stocknow fetch failed: {e}")
    errors += [f"{s}: no data from stocknow (check the trading code)" for s in syms if s not in data and not errors]
    OUT.mkdir(parents=True, exist_ok=True)
    for s, df in data.items():
        df.to_csv(OUT / f"{s}.csv")
    note = f"Source: stocknow.com.bd adjusted daily prices, fetched {date.today():%Y-%m-%d}"

results = {}
for s, df in data.items():
    try:
        results[s] = analyze(df, a.above, a.below)
    except Exception as e:  # one bad share must not hide the others
        errors.append(f"{s}: analysis failed: {e}")
        continue
    if not a.csv:  # a news/fundamentals failure is shown in the share's section; it does not fail the run
        try:
            co, results[s]["news"] = company_page(s)
            adjust_for_dividend(results[s], results[s]["news"])
        except (OSError, ValueError, KeyError) as e:
            co, results[s]["news"] = None, f"news fetch from dse.com.bd failed: {e}"
        try:
            news_items = results[s]["news"] if isinstance(results[s]["news"], list) else []
            results[s]["fund"] = (fundamentals(co, results[s]["close"], news_items) if co else
                                  "no company figures found on the dse.com.bd page (layout may have changed)")
        except Exception as e:  # an odd company record must not stop the other shares or the page

            results[s]["fund"] = f"reading company figures from dse.com.bd failed: {e}"

if not a.csv and results:  # fetched shares keep a track record; one-off checks in their own log
    src = "one-off" if a.symbols else "watchlist"
    log = OUT / ("one_off_forecast_log.csv" if a.symbols else "forecast_log.csv")
    scores = score_forecasts(log_forecasts(results, log), {s: df.close for s, df in data.items()})
    for s in results:
        results[s]["score"], results[s]["score_src"] = scores.get(s, {}), src

render(results, a.out, note, errors, latest_regime(), rates_status())
for s, r in results.items():
    fired = [x["rule"] for x in r["alerts"] if x["fired"]]
    print(f"{s} {r['date']} close {r['close']:,.2f} trend {r['trend']} | alerts: {', '.join(fired) or 'none'}"
          f" | secrets: {'; '.join(x['flag'] for x in r['secrets']) or 'none'}")
for e in errors:
    print("ERROR", e, file=sys.stderr)
print("page:", Path(a.out).resolve())
sys.exit(1 if errors else 0)
