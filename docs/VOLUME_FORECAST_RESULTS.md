# Volume and price: forecast test results

Run 2026-11-05 as pre-registered in docs/VOLUME_FORECAST_PREREG.md (`python -W ignore scripts/volume_forecast.py`,
output results/volume_forecast.csv). Data: DSE 2014 to 2026-11-04; A = 2014–2022, B = 2023 to Jan 2026,
C = 25 Jan to 4 Nov 2026 (fresh). R = today's traded value / its prior 20-session average.

## Answer in one line
Volume says **how far** a stock will move, not **which way**, with one small exception: heavy selling days.

## Direction (bar: t ≥ 2.64 in A, same sign in B and C)
| Test | Mean excess vs market A / B / C | t in A | Verdict |
|---|---|---|---|
| High-volume up day (R ≥ 2), next 5 days | +0.26% / +0.44% / +0.12% | 1.80 | NO: below the bar and far below the 1.1% trading cost |
| High-volume up day, next 20 days | −0.22% / −0.35% / +0.38% | −1.34 | NO |
| High-volume down day, next 5 days | lagged 0.17% / beat 0.22% / flat | 3.07 | WEAK: did not hold in B or C |
| **High-volume down day, next 20 days** | **lagged 0.70% / 0.63% / 0.93%** | **3.87** | **FORECASTS (small)** |
| Rank of volume × day direction vs next 5 / 20 days | mixed signs | 1.16 / 0.58 | NO |

The one pass: a stock that falls on at least double its usual turnover tends to trail the market by about 0.6–0.9%
over the next 20 sessions, in every period. The B and C t-stats are only ~1, and overlapping 20-day windows inflate
t, so treat it like teaching #2: a caution flag. It cannot be traded on the DSE (no short selling).

## Size (bar: t ≥ 2.24 in A, same sign in B and C)
| Test | Mean daily rank correlation A / B / C | t in A | Verdict |
|---|---|---|---|
| Volume ratio vs size of the next 5-day move | 0.115 / 0.121 / 0.124 | 28.2 | **LARGER MOVES** |
| Volume ratio vs size of the next 20-day move | 0.066 / 0.086 / 0.052 | 16.6 | **LARGER MOVES** |

Higher volume than usual is reliably followed by bigger moves, up or down, on 74% of days in A and 81% in C. The
watch page's price range uses the last 250 sessions and ignores this, so on high-volume days it is likely too
narrow. Widening it would be a separate change, tested first (coverage by volume bucket in scripts/forecast_check.py).
