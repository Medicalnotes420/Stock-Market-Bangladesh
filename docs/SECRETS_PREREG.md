# "My Secret Series" rules: Pre-registration (written before any backtest of them)

Fixed on 2026-10-29. This runs on the same engine, costs, risk limits, data periods, walk-forward and survival criteria as docs/PHASE4_PREREG.md, including changes 1–4 (kill-switch criterion, switching cost, 10% impact cap, volatility-scaled impact). Differences:

- **Data:** full-market data only, ending 2026-01-22 (the end of A2). The later DSE copies cover just 2 stocks and are excluded.
- **Settings:** regime filter {on, off} × gap exclusion **on only**. That's 2 settings per grid point.
- **Chance correction:** the 132 Phase 4 variants are counted too. n_trials = 132 + 90 = **222**, and sr_var is computed across all 222.
- **Held-out 2023–2026:** already seen in Phase 4, so it can only reject.
- **Applied in every rule:** the author's #38 "dry" filter. No entry when 20-day mean traded value is below 10% of the 60-day mean.
- **Indicators:** standard definitions in `dse_quant/indicators.py` (RSI 14, MACD 12/26/9, Bollinger 20/2, MFI 14 using traded value, Aroon Up 25, ADX/DI 14, SMA). Where the author gives no number, I picked the values below before seeing any result.

## Rules and grids
| Id | Tips | Entry (at close t, filled t+1) | Exit | Grid | Points |
|---|---|---|---|---|---|
| S1 | #1, #13 | RSI hit ≥ 90 within the last L sessions, and today 60 ≤ RSI ≤ 72 | after `hold` sessions (author: T+2) | L {5,10,15} × hold {2,3,5} | 9 |
| S7 | #7, #32 | Price range over the prior 15 sessions ≤ rng; today's value ≥ mult × its 15-session mean; today's return +2% to +6% | after `hold` | mult {2,3} × rng {5%,8%} × hold {3,5} | 8 |
| S25 | #25, #30 | Bollinger width ≤ its q-quantile over the prior 120 sessions; 15-session price range ≤ rng; MFI 50–80 and higher than 3 sessions ago | after `hold` (author: T+6/7) | q {0.1,0.2} × rng {3%,5%} × hold {6,7} | 8 |
| S23 | #23 | 10-session price change within ±flat; MFI up ≥ X points over 10 sessions | after `hold` (author: T+6/7) | X {10,20} × flat {2%,4%} × hold {6,7} | 8 |
| S67 | #67, #96, #3, #21, #2 | SMA13 crosses above SMA19; optional #96 filter (+DI > −DI, +DI up and −DI down over 3 sessions, MFI > 60, close ≤ 1.1 × SMA19) | #3 SMA13 crosses below SMA19, **or** #21 Aroon Up < 90, **or** #2 MACD line crosses below its signal line | filter {off,on} × exit {cross, aroon, macd} | 6 |
| S98 | #98 | Range over the last n sessions ≤ R and close in the bottom 20% of it | close in the top 20% of the current range | R {12%,15%,20%} × n {120,250} | 6 |

Total: 45 grid points × 2 settings = **90 variants**.

No stop-loss or profit target is added beyond the exits listed above. The engine's other limits (minimum hold T+2, lock days, caps, daily-loss gate) still apply.

## Claim check (descriptive, not a strategy)
**#62/#64 "top side flash":**
- **Definition:** a day with traded value ≥ 3× its prior 20-session mean and a close ≥ +5%.
- **Author's claim:** the next 2 sessions do not trade above the flash day's high.
- **What gets reported:** how often the claim holds, and how often the close 3 sessions later is above the flash day's close. Universe: eligible stocks, 2014–2022.

## Not run
- **#49 dead-bounce retrace and #59 Gann days:** the author gives no testable entry or exit.
- **#6 Ramadan:** needs verified Ramadan dates for every year.
- **#31 and #39 sell-half / RSI-97 exits:** they apply only to rare runaway trends, and no entry rule is attached to them.

## Survival criteria
The same seven as PHASE4_PREREG.md, verdicts SURVIVES / WEAK / REJECT. Any survivor is labelled "post-hoc data, pre-registered rule": the data was used before, the rules were not.
