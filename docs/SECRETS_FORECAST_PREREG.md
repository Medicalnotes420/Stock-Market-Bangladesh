# "My Secret Series": forecast test and fresh-2026 test (pre-registration)

Fixed on 2026-11-05, before either test was run. Rules and parameters come from docs/SECRETS_PREREG.md and the
walk-forward choice for the held-out period in results/secrets_table.csv (`held_params`). Nothing is tuned here.

## Why a second test
The first test (docs/SECRETS_RESULTS.md) asked "does trading the rule make money?". This one asks the question
behind using the teachings to forecast: **when a rule fires on a stock, does that stock then move the way the
author says, more than other stocks on the same day?** It also uses data no test has seen: full-market days
2026-01-25 to 2026-11-04 from stocknow.com.bd (fetched 2026-11-05, OHLCV identical to dse.com.bd on 361 checked rows).

## Test 1: forecast accuracy per signal
Signal days: a stock is eligible (`eligible_mask`) and the signal fires at close t. Entry signals also need the
#38 dry filter clear, as in the strategies. Up = the author buys; down = the author sells.

| Id | Signal (as in dse_quant/strategies.py / paper/harness.py) | Predicts | Horizon h (sessions) |
|---|---|---|---|
| S1 | RSI ≥ 90 within 5 sessions, now 60–72 | up | 2 |
| S7 | 15-session base ≤ 5%, value ≥ 2× its 15-session mean, day +2% to +6% | up | 5 |
| S25 | Bollinger width ≤ 10% quantile of prior 120, 15-session range ≤ 3%, MFI 50–80 and rising | up | 7 |
| S23 | 10-session price change within ±4%, MFI up ≥ 20 points | up | 7 |
| S67 | SMA13 crosses above SMA19 | up | 10 |
| S67+96 | S67 with the #96 checklist | up | 10 |
| S98 | 250-session range ≤ 12%, close in its bottom 20% | up | 20 |
| X2 | MACD line crosses below signal (#2) | down | 5 |
| X3 | SMA13 crosses below SMA19 (#3) | down | 5 |
| X21 | Aroon Up falls below 90 today (#21) | down | 5 |
| X31 | Close above upper Bollinger band and RSI > 75 (#31) | down | 5 |
| X39 | RSI ≥ 97 (#39) | down | 5 |

Measured from adjusted close t to close t+h. A signal day is dropped if a gap flag (unexplained price jump) falls
in t+1..t+h, or the stock has no close at t+h.
- **Excess return** = the stock's h-day return minus the mean h-day return of all eligible stocks that day,
  signed so that positive = moved the predicted way.
- **t-stat** over dates: average the signed excess per signal date, then mean / (sd / √dates). This stops one
  busy day from counting as hundreds of independent forecasts.
- **Hit rate** = share of signal days that moved the predicted way (raw return), shown next to the base rate
  for all eligible stock-days.
- Periods: **A** 2014–2022 (history), **B** 2023-01-01 to 2026-01-22 (held-out, seen before), **C** 2026-01-25
  onward (fresh).

**Verdict per signal:** FORECASTS if all of these hold:
1. Signed excess > 0 with t ≥ 2.87 in A (2-sided 5% after Bonferroni for 12 signals).
2. Signed excess > 0 in B and in C.
3. For up signals, mean signed excess in A ≥ 1.1% (a round trip at 0.47% each way plus the 0.10% minimum impact).
   Down signals have no cost bar, because selling is the exit you pay for anyway.

Otherwise WEAK if 1 holds but 2 or 3 fails, and NO otherwise. Period C is ~9 months; on its own it can only
reject.

## Test 2: the six rules traded on the fresh period
The same engine and config as docs/SECRETS_PREREG.md (gap exclusion on, regime filter on and off), each rule
with its `held_params`, run on the full panel. Then the 2026-01-25 to 2026-11-04 slice is reported: Sharpe,
total return, max drawdown, trades closed in the slice, and DSEX over the same days.

This can reject the WEAK S67 + #96 (regime on) result: it is rejected if its Sharpe in C is ≤ 0. A positive C
does not upgrade it, since 9 months is too short.

## Known limits
- Bonus shares and splits after January 2026 are not in the adjustment data. Their jumps are gap-flagged and dropped.
- In C, stocknow has no traded value. Value is close × volume, which only affects the #38 dry filter, MFI and
  eligibility (median value).
- DSEX for 2026-11-01 to 2026-11-03 is proxy-filled (regime only).
