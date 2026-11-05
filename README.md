# DSE research and paper-trading system

Research and paper trading for Dhaka Stock Exchange stocks: a daily signal generator you execute by hand. Long-only. Nothing connects to a broker.

**Status:** no strategy passed Phase 4 (docs/PHASE4_RESULTS.md). The paper harness tracks S67 forward (SMA13/19 cross + #96 checklist, WEAK in docs/SECRETS_RESULTS.md) with automatic stops; `--strategy none` turns it off. S67 picks from the whole liquid market, so it trades only on days with full-market data.

## Setup
```
pip install -r requirements.txt
```
Raw data (CC BY 4.0, Mendeley) goes in `data/raw/` and is not in git; see docs/PHASE3_DATA.md for the two dataset DOIs and exact paths.

Newer days come from copies of DSE's Data Archive (personal use) in `data/raw/dse/`: `dayend_<CODE>_<from>_<to>.csv` per watched stock and `market_summary_<from>_<to>.csv`. Rerun `build_clean.py` after adding files. These days carry no market breadth, so the regime shows "(no breadth data)" and the gate stays closed for `missing_data`.

## Run, in this order
```
python -m unittest discover -s tests -t .   # all tests
python scripts/build_clean.py               # data/raw -> data/clean (~2 min)
python -W ignore scripts/run_phase4.py      # backtests -> results/ (~3 min)
python scripts/paper_run.py                 # daily paper run -> data/paper/ (open data/paper/status.html)
```
Stocks for the status page's watchlist go in `watchlist.txt`, one DSE trading code per line.
`paper_run.py --replay N` replays the last N sessions. It needs a fresh `data/paper/` folder, because the harness refuses dates older than its last run.

## Docs
docs/PHASE1_SPEC.md (venue facts, regime, risk limits) · PHASE2_PLAN.md · PHASE3_DATA.md · PHASE4_PREREG.md · PHASE4_RESULTS.md · PHASE5_HARNESS.md · DSEX_PATTERNS_PREREG.md / DSEX_PATTERNS_RESULTS.md (index-level patterns)
