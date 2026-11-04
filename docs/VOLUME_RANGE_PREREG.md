# Widening the price range on high-volume days (pre-registration)

Fixed on 2026-11-05, before the test was run. Follows docs/VOLUME_FORECAST_RESULTS.md, which found that 2x+
volume is followed by bigger moves. Question: is the watch page's 80% range (`dse_quant.watch.forecast`) too
narrow on those days, and does a fixed widening fix it on data it was not fitted on?

## Setup
- Range exactly as `scripts/forecast_check.py`: 10%/50%/90% quantiles of the stock's own past h-session log moves
  over the last 250 sessions (at least 125), moves spanning a gap flag dropped. h = 5 and 20.
- Checked on **every** eligible stock-day (not every 10th), so high-volume days have enough cases.
  Realised move = log close t+h / close t; days with a gap flag in t+1..t+h are dropped.
- **R** = traded value at t / mean over t-20..t-1, as in docs/VOLUME_FORECAST_PREREG.md.
  Buckets: R < 0.5, 0.5–1, 1–2, ≥ 2.
- Periods: A 2014–2022 (fit), B 2023 to 2026-01-22, C 2026-01-25 onward (fresh).

## Test 1: coverage by volume bucket
Share of stock-days where the realised move lands inside the range, plus below / above, per bucket, h and period.
Reported for all buckets; only R ≥ 2 is acted on.

## Test 2: widened range on R ≥ 2 days
Widen each side away from the middle by factor k: low' = mid − k·(mid − low), high' = mid + k·(high − mid),
in log space. k is picked **on period A only**: the smallest k in {1.0, 1.1, …, 3.0} whose R ≥ 2 coverage in A is
≥ 80%, separately for h = 5 and h = 20. Then k is frozen and applied to B and C.

**Verdict ADOPT** (for that h) if all hold:
1. Unwidened R ≥ 2 coverage in A is below 75% (the problem is real, not 1–2 points).
2. With k, R ≥ 2 coverage in B and in C is between 75% and 85%.
3. With k, R ≥ 2 coverage in B and in C is closer to 80% than unwidened.

Otherwise NOT ADOPTED. ADOPT only means the page change is justified; it is made separately, with a test.
Because the watch page shows share volume, not value, an adopted rule would use volume / 20-session volume
average there (the same over 20 sessions unless a bonus issue falls inside, which the page would show as a spike).

## Known limits
- Neighbouring stock-days overlap, so coverage figures carry more uncertainty than their counts suggest.
- Misses are mostly below the range (forecast_check). A symmetric widening does not fix that skew.
