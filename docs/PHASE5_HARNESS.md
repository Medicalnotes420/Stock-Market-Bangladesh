# Phase 5 — Paper-Trading Harness (no strategy enabled)

Status: DRAFT for approval · 2026-10-29

No strategy passed Phase 4, so the harness runs with **no strategy enabled**. Every day it reports cash and an empty order file. It is ready for a strategy once one passes a fresh Phase 4 test.

## Daily run (after the DSE close, ~16:00 BST)
`python scripts/paper_run.py` (or `--asof YYYY-MM-DD`, or `--replay N` for the last N sessions)

1. Load the clean data and keep the last 500 sessions (`dse_quant/paper/harness.py`).
2. **Data checks** (`data/checks.data_status`): is the latest bar the expected day, what share of yesterday's eligible universe is missing, is DSEX present?
3. **Regime** (`regime.inputs` + `classify`), using the same code as the backtest. Moving the code into `regime.py` was checked: the regime counts are identical to the Phase 4 run, and the 500-session window gives the same regime as full history on all 10 replay days.
4. **Risk gate / kill switch** (`risk.RiskGate`): daily loss, drawdown, stale or missing data. A kill or a STRESS regime writes an exit list (slowest exit first) into the order file.
5. **Orders:** `data/paper/orders/orders_<date>.csv`. Always empty while no strategy is enabled.
6. **Journal:** one JSON line per run, appended to `data/paper/journal.jsonl`. It records run time, as-of date, inputs hash, data status, regime, gate reasons, kill, exit list, orders and equity. Any input error is journaled as an alert and closes the gate. It never skips the journal.
7. **State:** `data/paper/state.json` holds cash, positions and peak equity. Paper only; nothing connects to a broker.

## Monitoring (`dse_quant/paper/monitor.py`, printed after each run)
| Metric | Alert |
|---|---|
| Runs, days the gate was open, gate-close reasons | — |
| Regime distribution | — |
| Equity, max drawdown | Kill switch fired → "exit list written, no new signals" |
| Consecutive stale-data days | ≥ 3 → "data feed broken" |
| Runs with input errors | any → alert |

## Automatic stop rules for any future strategy (to be wired in before it is enabled)
A strategy is stopped automatically, and an exit list is written, when any of these happens:
1. The 15% drawdown kill switch fires (already enforced).
2. After 60 live sessions, its realised Sharpe is below the 5th percentile of its own bootstrapped walk-forward Sharpe.
3. Average realised cost per side is more than 2× the model (needs your actual fills).
4. More than 20% of intended exits are blocked by lower-limit locks in a month (liquidity trap).
5. The data feed is stale for 3+ sessions while the strategy holds positions.

## Evidence
- `python -W ignore -m unittest discover -s tests -t .` gives **84 tests OK**. There are 6 new tests: healthy day, stale data, corrupt input (no exception, gate closed), kill-switch exit list, append-only journal with persistent state, and the monitor's broken-feed alert.
- `python scripts/paper_run.py --replay 10` (22 s): 2026-01-11 → 2026-01-22. Regime was RISK_OFF on 9 days and NEUTRAL on 1. The gate was open on 6 days and closed on 4 for `missing_index` (DSEX absent in the data on those days). There were 0 orders.
- `python scripts/paper_run.py` (as of 2026-10-29): gate CLOSED for `stale_data`, `missing_data` and `missing_index`, because the data ends 2026-01-22. 0 orders.

## Open items
- **No daily data source is approved.** Options: DSE day-end pages (personal use, no `/api`), StockNow with written consent, or a licensed vendor. Until then the harness can only replay history.
- **Capital** is assumed to be Tk 1 crore.
- **Audit findings 4, 6, 7 and 8 are fixed:**
  - **4:** gap days are now counted per trade and reported.
  - **6:** one `risk.daily_loss_breached` is shared by the engine and RiskGate.
  - **7:** stop, trailing, target and regime-branch tests added, and a mutation check showed they catch a flipped stop comparison.
  - **8:** the stale log is deleted.

## S67 paper tracking (added 2026-10-30, stopped 2026-11-05)
**Stopped:** S67 + #96 lost 4.3% on fresh 2026 data while DSEX gained 5.3%, which rejects it under the
pre-registered rule (docs/SECRETS_FORECAST_RESULTS.md). When it was stopped the book held no positions and no
orders. `paper_run.py` now defaults to `--strategy none`; `--strategy S67` still runs it.

- `dse_quant/paper/book.py`: fills the previous session's orders at today's typical price, with the same costs, T+2 and lock rules as the backtest. It then queues S67 exits and entries through `risk.check_order` and writes them to the order file.
- **Automatic stops** (`stop_checks`): 15% kill switch; stale data for 3 sessions while holding; more than 20% of the last 20 exits blocked by lower locks; live Sharpe below 0 after 60 sessions (a shortcut, until a bootstrap band exists). A stopped book only exits.
- **Check:** a paper replay of Mar–Jun 2021 took the same 4 trades as the backtest engine, on the same entry and exit dates, plus 2 more, because the engine started earlier with different holdings.
