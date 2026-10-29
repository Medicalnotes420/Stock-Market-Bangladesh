# Phase 2 — Architecture and Build Plan

Status: DRAFT for approval · 2026-10-29

## Constraints that shape the design
- Paper trading only. Nothing imports a broker library or opens a network socket except the Phase 3 data fetcher, and that only for a source you approve.
- Daily end-of-day batch run. The system emits signals; you place any trades by hand (Phase 1 §1).
- Dependencies: Python 3.15 stdlib, plus `pandas` and `numpy`, which are already installed. Tests use stdlib `unittest`. `pytest` is not installed, and per your rules I won't add it unasked. Parquet would need `pyarrow`, so storage is CSV until you approve otherwise.
- Signals, risk and execution are separate layers. Strategies output *desired target weights* only. Only `risk.py` turns them into allowed quantities.

## Repo structure

```
Stockapp/
  docs/                    PHASE1_SPEC.md, PHASE2_PLAN.md, later phase reports
  dse_quant/
    risk.py                [BUILT] hard limits, RiskGate, vol-target sizing, kill-switch exit list
    calendar.py            [Ph3] trading-day calendar derived from data; macro-event CSV loader
    data/
      sources.py           [Ph3] one fetcher per approved source; raw files written untouched
      adjust.py            [Ph3] corporate-action adjustment (cash div, bonus, rights)
      checks.py            [Ph3] staleness, price-sanity vs circuit limit, missing-bar checks
      store.py             [Ph3] read/write CSV under data/raw and data/clean
    limits.py              [Ph3] DSE circuit-limit tiers; lower/upper lock detection
    universe.py            [Ph3] point-in-time liquidity/category filter (spec §4)
    regime.py              [Ph4] RISK_ON / NEUTRAL / RISK_OFF / STRESS (spec §3)
    strategies/            [Ph4] c1_momentum.py ... c5_div_drift.py, each: f(data up to t) -> target weights
    backtest/
      engine.py            [Ph4] next-day fills, lock-day no-fill, T+2 min hold, costs
      costs.py             [Ph4] commission + tax + turnover-scaled slippage, 1x/1.5x/2x
      metrics.py           [Ph4] Sharpe, MDD, win rate, PF, trades, deflated Sharpe, variant counter
      walkforward.py       [Ph4] time splits, rolling windows, parameter sweeps
    paper/
      harness.py           [Ph5] daily run: data -> checks -> regime -> signals -> RiskGate -> order list
      journal.py           [Ph5] JSON-lines decision log (inputs hash, outputs, later fills/P&L)
      monitor.py           [Ph5] live-vs-backtest drift metrics, auto-stop conditions
  tests/                   one test file per module; fixtures are small hand-built CSVs
  data/                    raw/ and clean/ (git-ignored), not created yet
  config/events.csv        [Ph3] macro calendar, hand-maintained
```

## Test suite plan
| Layer | What the tests prove |
|---|---|
| risk | limits clip and never enlarge orders; long-only; the gate blocks entries on loss, drawdown or stale data; exits always pass **(done, 23 tests)** |
| data/adjust | a known bonus or rights event gives a continuous adjusted series; raw files are never modified |
| leakage | each strategy's signal at day t is unchanged when the data after t is deleted or scrambled (look-ahead canary) |
| limits | a lower-lock day gives no sell fill; tier boundaries are correct at Tk200, 500, 1000, 2000 and 5000 |
| universe | a delisted stock is present before its last day and absent after; Z category is excluded on the day of reclassification |
| backtest | a hand-computed 3-trade example matches the engine's P&L to the taka, costs included |
| paper | a corrupt or stale input file produces no orders and an alert, never an exception that skips the checks |

Run all of it with: `python -m unittest discover -s tests -t .`

## Build order
1. **Phase 2 (this):** `risk.py` first. It is the layer every other output passes through, and it needs no data.
2. **Phase 3:** calendar, limits, data fetch, adjust, checks, universe. Tests come before code. This needs your data-source choice.
3. **Phase 4:** costs, engine, metrics, regime, 5 strategies, walk-forward, comparison table.
4. **Phase 5:** paper harness, journal, monitor, auto-stop rules.

## Decisions taken without your input (say if you disagree)
- No `git init` yet. I recommend it before Phase 3 so every result maps to a commit.
- A sell is always allowed through the gate. Only buys are blocked when it closes.
- The kill-switch exit list is ordered slowest-to-exit first, because the illiquid names need the most sessions.
- The limits are frozen in code (`Limits` dataclass). Changing one means editing `risk.py`.
