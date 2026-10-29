# Phase 4 — Results

Status: for your decision · 2026-10-29 · Code at commit 6554d96 · Rules in docs/PHASE4_PREREG.md
Command: `python -W ignore scripts/run_phase4.py` (191 s). Raw output: results/phase4.log, results/phase4_table.csv, results/phase4_variants.csv.

## Comparison table (pre-registered rules, 1x costs, walk-forward out-of-sample 2017–2022)
Each row covers 4 settings (regime filter on/off × gap exclusion on/off). Ranges run from the worst setting to the best.

| Strategy | Edge (one line) | Timeframe | OOS Sharpe | OOS Max DD | OOS Trades | Sharpe at 1.5x / 2x cost | Verdict |
|---|---|---|---|---|---|---|---|
| C1 Momentum | Slow news diffusion: winners keep winning | ~1–3 months | −1.23 … −0.98 | 25% … 73% | 60 … 309 | −1.52 … −1.29 / −1.70 … −1.48 | REJECT (4/4) |
| C2 Breakout | A break above the 60-day high on a value surge signals new information | 2–6 weeks | −1.72 … −0.91 | 57% … 85% | 184 … 337 | −2.09 … −1.36 / −2.31 … −1.66 | REJECT (4/4) |
| C3 Reversal | Panic selling overshoots in liquid names | 3–10 sessions | −2.86 … −2.03 | 20% … 80% | 66 … 333 | −3.29 … −2.43 / −3.60 … −2.65 | REJECT (4/4) |
| C4 Low-vol (no dividend filter) | Retail lottery preference overprices volatile junk | Quarterly | −0.46 … −0.42 | 32% … 51% | 22 … 51 | −0.63 … −0.49 / −0.62 … −0.49 | REJECT (4/4) |
| C5 Dividend drift | Underreaction to dividend declarations | Weeks | not run | not run | not run | not run | not run (no disclosure timestamps) |
| Benchmark: DSEX buy-and-hold | — | — | 0.32 | 43% | — | — | — |

Every variant fails every criterion (`nnnnnnn`). No training grid point has a positive Sharpe (neighbourhood = 0.0). The deflated Sharpe probability is 0.00 everywhere. The 15% kill switch fires out-of-sample in all 16 rows. Held-out 2023–2026: all negative, ranging from −2.27 to −0.70 (DSEX benchmark −0.38).

Other evidence from the same run:
- **Proxy index vs DSEX:** daily correlation 0.885 over the 2,597 days where both exist. 340 missing DSEX days were filled with the proxy.
- **Regime days:** RISK_ON is rare, with 0 days in 2023 and 2024 (results/phase4_regime_counts.csv). With the regime filter on, the strategies mostly sit in cash.
- **Chance correction:** 132 variants, variance of per-period Sharpe across variants recorded in results/phase4_meta.json.

## Why this table cannot be taken at face value: the cost model is wrong
Diagnostic run with one parameter set per strategy, regime off, gap exclusion on, 2017–2022, **not walk-forward**. Script: scratchpad diag4.py, not committed.

| | Sharpe, costs off | Sharpe, costs 1x | Mean trade, costs off → 1x |
|---|---|---|---|
| C4 low-vol (250d, top 10) | 0.47 | −0.16 | +6.7% → −3.5% |
| C1 momentum (252d, top 10) | 0.30 | −1.28 | +0.65% → −3.5% |
| C3 reversal (−10%, 7d) | 0.06 | −2.92 | +0.13% → −5.1% |
| Equal-weight eligible universe (no costs, close-to-close) | 0.17 | — | — |

Costs eat 4–10% per round trip, against about 1.2% expected. The cause is the registered impact term `0.5·√(order/ADTV)` (Phase 1 spec, written by me). It leaves out the stock's daily volatility. The standard square-root model is `k·σ_daily·√(order/ADTV)`. Checked in code:

| Order vs ADTV | Impact as registered (per side) | With σ = 2.5%/day, k = 1 |
|---|---|---|
| Tk 10 lakh vs Tk 5 crore | 7.07% | 0.35% |
| Tk 10 lakh vs Tk 20 crore | 3.54% | 0.18% |
| Tk 2 lakh vs Tk 5 crore | 3.16% | 0.16% |

So the pre-registered verdict (all REJECT) stands as recorded. What it mostly proves is that the cost model was unrealistic, not that the strategies are dead.

## What the costs-off numbers already say (bear case)
- Even with **zero costs**, no single parameter set reaches the 0.5 Sharpe bar. C4 comes closest at 0.47. C1 is at 0.30, C3 at 0.06, and the plain universe at 0.17. The edges, if they exist, are thin.
- **C3 reversal** has a +0.13% mean trade before costs. It cannot survive any realistic round trip of about 1.2% or more. It is dead regardless of the cost fix.
- **C4** holds for about 6 months and trades about 14 times a year, so it is the only candidate whose edge (+6.7% mean trade before costs) is large next to realistic costs. Its worst trades are large single-stock drops: BRACBANK −43% in 2019–20, IFADAUTOS −30%.
- **Held-out has now been opened once.** Any rerun can use it only to reject, never to rescue (pre-registration, criterion 7).

## Run 2: corrected cost model (POST-HOC, change 4)
Code at fb870e2. Impact is now `σ_daily·√(order/ADTV)`; everything else is unchanged. Command and output paths are the same as run 1 (results/ now holds run 2; run 1 is in git at 21ed7f3).

| Strategy | Edge | Timeframe | OOS Sharpe | OOS Max DD | OOS Trades | Sharpe at 1.5x / 2x cost | Kill switch fired (OOS) | Sharpe without floor periods | Held-out Sharpe | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 Momentum | slow diffusion | 1–3 months | −0.27 … 0.26 | 10% … 42% | 60 … 275 | −0.45…0.03 / −0.62…−0.19 | 2 of 4 settings | −0.32 … 0.05 | −1.09 … −0.58 | REJECT (4/4) |
| C2 Breakout | new information on a value surge | 2–6 weeks | −0.44 … 0.19 | 21% … 46% | 212 … 304 | −0.69…−0.02 / −0.92…−0.23 | 4 of 4 | −0.61 … 0.05 | −0.70 … −0.64 | REJECT (4/4) |
| C3 Reversal | panic overshoot | 3–10 sessions | −1.18 … −1.05 | 13% … 48% | 96 … 389 | −1.64…−1.34 / −2.05…−1.53 | 2 of 4 | −1.36 … −1.00 | −1.14 … −0.91 | REJECT (4/4) |
| C4 Low-vol | retail lottery preference | quarterly | 0.11 … 0.35 | 24% … 32% | 21 … 80 | 0.04…0.29 / −0.02…0.18 | 4 of 4 | −0.28 … −0.08 | −0.59 … −0.05 | REJECT (4/4) |
| C5 Dividend drift | underreaction | weeks | not run | not run | not run | not run | — | — | — | not run (no data) |
| DSEX buy-and-hold | — | — | 0.32 | 43% | — | — | — | — | −0.38 | benchmark |

Highest out-of-sample row: **C4, regime off, gap exclusion on**.
- Sharpe 0.35, max drawdown 30%, 80 trades, profit factor 1.97.
- Sharpe at 1.5× cost 0.29, at 2× cost 0.18.
- Deflated Sharpe probability 0.05.
- The kill switch would have fired on 2019-05-12.
- **Without the floor-price periods its Sharpe is −0.14.** Held-out: −0.07.

It passes criteria 2 (positive at 1.5× costs) and 3 (neighbourhood). It fails 1 (Sharpe ≥ 0.5), 4 (deflated Sharpe), 5 (kill switch), 6 (floor periods) and 7 (held-out).

### Trades held through an unexplained price gap (audit finding 4)
Column `oos_trades_through_gap`: share of out-of-sample trades that held a stock through a day flagged as an unexplained gap. Their P&L may include a missed bonus or rights adjustment.
- C1–C3: 1.0–2.2% of trades.
- **C4: 8.3–14.3%**, because its long holds cross more gap days. So C4's results carry the most data noise in either direction.

This was added by a later rerun (after audit fixes 4 and 6). Every previously reported column is identical to run 2.

## Conclusion
**No strategy survives, under either cost model.**
- The strongest candidate (C4 low-vol) roughly matches DSEX on risk-adjusted return: 0.35 vs 0.32, with a smaller drawdown (30% vs 43%).
- Its positive results come from the regulator floor-price periods, when falling prices were blocked by rule.
- It is negative held-out and in the rest of the history.
- The regime filter mostly keeps the strategies in cash (RISK_ON: 0 days in 2023–24). It does not rescue anything.
- None of these strategies goes into paper trading as a candidate.
