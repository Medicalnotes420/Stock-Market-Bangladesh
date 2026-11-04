# "My Secret Series": forecast test and fresh-2026 test (results)

Status: for your decision · 2026-11-05 · Tests fixed in docs/SECRETS_FORECAST_PREREG.md (commit 0a20ddc) before
this run. Command: `python -W ignore scripts/secrets_forecast.py` (60 s). Output: results/secrets_forecast.csv,
results/secrets_fresh.csv.

## Test 1: does the stock move the way the author says?
Excess = the stock's move over h sessions minus the average eligible stock's move on the same days, signed so
**positive = the author was right**. A = 2014–2022, B = 2023 to Jan 2026, C = Jan–Nov 2026 (fresh, never tested).

| Signal | Author says | h | Signals A / B / C | Excess A | t (A) | Excess B | Excess C | t (C) | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| S1 RSI 90 → 70 pullback (#1, #13) | up | 2 | 28 / 9 / 3 | −0.53% | −0.3 | −0.49% | +0.36% | 0.2 | NO |
| S7 turnover surge after flat base (#7, #32) | up | 5 | 548 / 86 / 55 | −0.21% | −0.9 | −1.25% | +0.20% | 0.5 | NO |
| S25 Bollinger squeeze (#25, #30) | up | 7 | 717 / 137 / 91 | +0.26% | 0.8 | +0.37% | +2.17% | 3.8 | NO |
| S23 MFI rising, price flat (#23) | up | 7 | 8,172 / 2,032 / 801 | −0.18% | −1.4 | −0.08% | −0.05% | −0.9 | NO |
| S67 SMA13 × SMA19 cross up (#67) | up | 10 | 3,614 / 980 / 434 | +0.07% | 1.8 | +0.47% | −0.67% | −1.6 | NO |
| S67 + #96 checklist | up | 10 | 859 / 191 / 118 | −0.02% | −0.1 | −0.12% | −1.01% | −1.3 | NO |
| S98 lazy range, bottom 20% (#98) | up | 20 | 43 / 91 / 0 | +0.48% | 0.9 | +0.73% | — | — | NO |
| **X2 MACD crosses below signal (#2)** | **down** | 5 | 4,359 / 1,180 / 604 | **+0.26%** | **3.6** | **+0.03%** | **+0.53%** | 2.0 | **FORECASTS** |
| X3 SMA13 crosses below SMA19 (#3) | down | 5 | 4,047 / 1,075 / 520 | +0.25% | 2.4 | +0.08% | −0.02% | −0.9 | NO |
| X21 Aroon Up falls below 90 (#21) | down | 5 | 3,580 / 821 / 532 | +0.24% | 1.8 | +0.28% | +0.40% | 1.2 | NO |
| X31 above upper band, RSI > 75 (#31) | down | 5 | 2,000 / 448 / 277 | **−1.62%** | **−6.6** | **−2.77%** | **−1.24%** | **−3.2** | NO (opposite, see below) |
| X39 RSI ≥ 97 (#39) | down | 5 | 7 / 0 / 0 | −22.7% | −5.4 | — | — | — | NO |

Chance correction: the A t-stat must reach 2.87 (5% two-sided over 12 signals).

### What this says
- **No buy signal forecasts a rise.** All seven of the author's entry signals fail. None beats the average stock in
  2014–2022 by a significant margin, let alone by the 1.1% a round trip costs.
  - S25's +2.17% in 2026 (t 3.8) has no support in the 12 earlier years (t 0.8). Nine months of one rule after
    12 tries is not evidence.
- **One sell signal works, slightly: #2 (MACD line crosses below its signal line).** In the 5 sessions after it,
  the stock lags the market by 0.26% on average (t 3.6). It also lags in 2023–26 and in fresh 2026, so it
  passes. It is small: it's a reason to be cautious about a stock you already hold, not something to profit from.
  DSE has no short selling, so you can't trade it directly.
- **#31 runs backwards.** The author says to sell (half) when the price closes above the upper Bollinger band
  with RSI above 75. In every period, those stocks went on to **beat** the market by 1.2–2.8% over 5 days,
  significantly so (t −6.6, −5.4, −3.2). #39 (RSI 97+) points the same way, but there are only 7 cases.
  - This is a post-hoc observation: the test was set up to check the author's direction, not this one. Any use
    of it needs its own pre-registered test with costs.
- **Hit rates:** the "base hit rate" for up is ~41%, not 50%, because many DSE stock-days don't move at all.
  Compare each signal's hit rate with that base, not with 50%.

## Test 2: the rules traded on fresh 2026 data (2026-01-25 to 2026-11-04)
| Rule (held-out params) | Regime filter | Sharpe | Return | Max DD | Trades | Win rate |
|---|---|---|---|---|---|---|
| S1 | on / off | 0.00 / −0.67 | 0.0% / −0.2% | 0% / 0.3% | 0 / 1 | — / 0% |
| S7 | on / off | −0.95 / −1.88 | −2.1% / −7.4% | 3% / 9% | 18 / 47 | 33% / 38% |
| S25 | on / off | −1.71 / −0.07 | −1.7% / −0.6% | 3% / 11% | 12 / 106 | 17% / 39% |
| S23 | on / off | −2.89 / −1.59 | −14.0% / −19.5% | 16% / 27% | 64 / 185 | 23% / 35% |
| **S67 + #96** | **on** | **−0.72** | **−4.3%** | **7%** | **25** | **36%** |
| S67 (+ #96, macd exit) | off | −2.83 | −22.7% | 27% | 96 | 25% |
| S98 | on / off | 0.00 / 1.59 | 0.0% / +5.0% | 0% / 3% | 0 / 4 | — / 25% |
| DSEX | — | 0.52 | +5.3% | — | — | — |

Regime days in this period: NEUTRAL 82, RISK_OFF 71, RISK_ON 32.

**S67 + #96 (regime on), the only earlier WEAK result, is REJECTED** under the pre-registered rule: its fresh
Sharpe is −0.72, below 0. It lost 4.3% while DSEX gained 5.3%. S98 regime-off is the one positive row, but on 4
trades, which tells nothing.

## Bottom line for forecasting
In 12 years of DSE data plus 9 fresh months, these teachings do not forecast which stocks will rise. One sell
warning (#2) has a small, real edge. One sell rule (#31) points the wrong way. The paper run still tracks S67 by
default (`scripts/paper_run.py --strategy S67`); whether to stop that is your call.

Limits:
- Daily data only: the author's screen reading isn't testable.
- Bonus shares and splits after January 2026 are not in the adjustment data (gap-flagged and dropped).
- In 2026, value is close × volume.
- Period C is short.
