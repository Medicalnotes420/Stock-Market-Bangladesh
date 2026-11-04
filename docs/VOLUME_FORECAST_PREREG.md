# Volume and price: forecast test (pre-registration)

Fixed on 2026-11-05, before the test was run. Same data, periods, excess-return method, gap handling and verdict
rules as docs/SECRETS_FORECAST_PREREG.md. Nothing is tuned; the thresholds below are round numbers picked once.

## Question
The watch page now shows today's volume against its 20-session average. Does that tell you anything about where
the price goes next, or how far it moves?

## Measure
**R** = traded value at close t / mean traded value over sessions t-20..t-1 (today left out). Traded value, not
share volume, because bonus shares and splits change share counts but not value. In period C value is
close × volume (stocknow has no value column). Stock-days with a zero or missing 20-session mean are dropped.
**Day move** = close t / close t-1 - 1 (adjusted).

## Direction tests (6, Bonferroni: t ≥ 2.64)
| Id | Signal at close t | Predicts | h |
|---|---|---|---|
| VU5, VU20 | R ≥ 2 and day move > 0 (high-volume up day) | up | 5, 20 |
| VD5, VD20 | R ≥ 2 and day move < 0 (high-volume down day) | down | 5, 20 |
| IC5, IC20 | Spearman rank correlation, across eligible stocks each day, of log R × sign(day move) with the h-day excess return | positive | 5, 20 |

Event signals (VU, VD) use the verdict rules of SECRETS_FORECAST_PREREG.md unchanged (t over dates ≥ 2.64 in A,
positive in B and C, up signals need ≥ 1.1% mean excess in A).
IC: FORECASTS if the mean daily IC is > 0 with t ≥ 2.64 in A and > 0 in B and C; WEAK if only A holds; NO otherwise.
No cost bar for IC, since it ranks stocks rather than naming a trade.

## Size test (2, Bonferroni: t ≥ 2.24)
| Id | Measure | h |
|---|---|---|
| MAG5, MAG20 | Spearman, across stocks each day, of log R with the absolute h-day excess return | 5, 20 |

LARGER MOVES if mean daily IC > 0 with t ≥ 2.24 in A and > 0 in B and C. If so, the watch page's price range
could be widened on high-volume days; that would be a separate change, tested first.

## Known limits
- R ≥ 2 includes news days (results, dividends, record dates); the test cannot tell those apart.
- Value in C is close × volume, so a bonus issue in C would distort R; those days are mostly gap-flagged and dropped.
- Overlapping h-day windows make neighbouring dates correlated; the t over dates overstates certainty somewhat,
  more at h = 20. The B and C checks guard against that.
