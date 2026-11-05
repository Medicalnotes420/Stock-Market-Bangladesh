# Fixing the low-side misses of the price range (pre-registration)

Fixed on 2026-11-05, before the test was run. `scripts/forecast_check.py` found that when the watch page's "80%"
range misses, the price lands below it about twice as often as above (h = 20: 16% below vs 6% above). A fair
range would miss about 10% each side. Question: does a simple change even out the misses on data it was not
fitted on, without hurting coverage?

## Setup (same as docs/VOLUME_RANGE_PREREG.md)
- Range: 10%/50%/90% quantiles of the stock's own past h-session log moves over the last 250 sessions (at least
  125), moves spanning a gap flag dropped. h = 5 and 20. Every eligible stock-day; realised move = log close
  t+h / close t, days with a gap flag in t+1..t+h dropped. No volume widening (it is symmetric about the middle,
  so it does not change the skew).
- Periods: A 2014–2022 (fit), B 2023 to 2026-01-22, C 2026-01-25 onward (fresh).

## Variants (log space)
| Id | Change | Fitted? |
|---|---|---|
| D0 | none (the current page) | – |
| D1 | **no own drift:** subtract the median past move from all three, so the middle is today's price | no |
| D2 | **fixed downward shift:** subtract s from all three; s from {0, 0.005, …, 0.100} picked on A only, per h, as the value giving the smallest \|below − above\| in A; then frozen | on A |

## Verdict (per h)
A variant **passes** if, in **both** B and C:
1. \|below − above\| is smaller than D0's, and
2. coverage is between 75% and 85%, and
3. coverage is no more than 2 points below D0's.

**ADOPT D1** if it passes (nothing fitted, so preferred). Otherwise **ADOPT D2** if it passes. Otherwise
**NOT ADOPTED**. An adopted change goes into `dse_quant.watch.forecast` separately, with a test.

## Known limits
- Neighbouring stock-days overlap, so the figures carry more uncertainty than their counts suggest.
- Falling years (2018, 2024) may still miss low; this test is about the average skew, not those years.
- D1 removes any real drift a share has; that is the point, but a steadily rising share's range will lag.
