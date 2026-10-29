# Phase 4 — Pre-registration (written before any backtest was run)

Fixed on 2026-10-29, before the first strategy backtest. Results must not change anything here. If something does change, the change is listed at the bottom with the reason.

## Data periods
- Full data: 2012-10-01 to 2026-01-22. The first 250 sessions are warm-up for the universe and volatility history.
- **Training/validation: 2014-01-01 to 2022-12-31.** Walk-forward: parameters are picked on the 3 prior calendar years, then applied to the next year. Out-of-sample years run 2017–2022.
- **Held-out: 2023-01-01 to 2026-01-22.** It uses the parameters walk-forward picks from 2020–2022. It is looked at once, in the final run.
- Floor-price periods (2020-03-19 → 2021-04-07 and 2022-07-28 → 2024-01-21): each strategy is also reported with these periods removed. A strategy that only works inside them is rejected.

## Fixed engine assumptions
- A signal at close t fills at t+1 at the typical price (O+H+L+C)/4, plus slippage.
- No sell fill on a lower-lock day. No buy fill on an upper-lock day or a day with no bar.
- Minimum hold of 2 sessions (T+2). Long-only, no leverage, cash earns 0.
- Sizing: 0.5% of equity at risk per 1×ATR(20). Caps from `risk.check_order`: 10% of equity per name, 5% of ADTV(20), at most 12 names. The sector cap is **not enforced** because there is no sector data.
- Daily-loss gate (−2%) from `risk.py`: no new entries the next session.
- Costs at 1×: 0.47% per side (commission 0.40 + tax 0.05 + misc 0.02) plus slippage `max(0.10%, 0.5·sqrt(order/ADTV20))`. Each strategy is re-run at 1.5× and 2×.
- A held stock with no bar for 60 sessions is **written off to zero** (assumed delisted).
- Universe: `UniverseRules()` defaults.

## Variants (counted for the chance correction)
Each strategy is run over its parameter grid × regime filter {on, off} × gap exclusion {on, off}.

| Strategy | Grid | Runs |
|---|---|---|
| C1 momentum | lookback {126,189,252} × top_n {5,8,10}, skip 21, rebalance 21 | 9×4 = 36 |
| C2 breakout | window {40,60,90} × value-surge multiple {1.5,2,3} | 36 |
| C3 reversal | 5-day drop {−8%,−10%,−12%} × max hold {5,7,10} | 36 |
| C4 low-vol | vol window {120,250} × top_n {8,10,12}, rebalance 63 | 24 |
| C5 dividend drift | **not run**: no timestamped disclosure data in the approved sources | 0 |

Total: **132 variants**. The deflated Sharpe ratio uses N = 132, plus the spread of Sharpe ratios across all variants.

Spec deviations forced by the data:
- C4 drops the "paid a cash dividend 2 years running" filter and becomes plain low volatility.
- The macro-calendar blackout is not applied because no event CSV exists yet.
- The C2 gap-up ≤3% entry rule is not applied.

## Survival criteria (ALL must hold, at 1× costs unless stated)
1. Walk-forward out-of-sample (2017–2022) Sharpe ≥ 0.5 and ≥ 30 round-trip trades.
2. Out-of-sample Sharpe > 0 at 1.5× costs.
3. Neighbourhood: across the training period, at least 2/3 of the grid points for that regime/gap setting have Sharpe > 0.
4. Deflated Sharpe probability ≥ 0.90 on the out-of-sample returns.
5. Out-of-sample max drawdown ≤ 25%.
6. Sharpe still > 0 with the floor-price periods removed.
7. Held-out (2023–2026) Sharpe > 0. It is checked last and can only reject, never rescue.

Verdicts:
- **SURVIVES**: all seven criteria pass.
- **WEAK**: criteria 1 and 5 pass but another fails.
- **REJECT**: anything else.

## Changes after registration
All three changes come from a code audit on 2026-10-29. An earlier run completed using the old rules, but its output was **not opened**, and the rerun overwrites it.
1. **Criterion 5:** "out-of-sample max drawdown ≤ 25%" becomes "the 15% drawdown kill switch never fires out-of-sample". The 25% bar let through strategies that the live system (risk.py, spec §6) would have shut down. This is stricter.
2. **Walk-forward switching cost:** when the chosen parameter set changes between years, the first day of the new year pays a full rotation, 2 × (0.47% + 0.10%) × cost multiplier. Previously this was free. Stricter.
3. **Impact cost capped at 10% per side:** previously uncapped, which allowed a sale to cost more than 100%. Less strict for very illiquid exits only.
