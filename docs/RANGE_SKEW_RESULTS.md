# Fixing the low-side misses of the price range: results

Run 2026-11-05 as pre-registered in docs/RANGE_SKEW_PREREG.md (`python -W ignore scripts/range_skew.py`,
output results/range_skew.csv). Every eligible stock-day, 2014 to 4 Nov 2026.

## Answer in one line
Moving the whole range down by a fixed amount (1% for 5 sessions, 3% for 20, fitted on 2014–22) evened out the
misses on later data and raised coverage. **Verdict: ADOPT D2 for h = 5 and h = 20.** Removing the share's own
drift (D1) did not fix the skew and failed.

## Coverage and misses (inside / below / above)
| h | Variant | A 2014–22 | B 2023–Jan 26 | C 2026 |
|---|---|---|---|---|
| 5 | D0 current | 80 / 12 / 7 | 76 / 15 / 9 | 81 / 12 / 7 |
| 5 | D1 no drift | 80 / 13 / 7 | 76 / 16 / 9 | 82 / 11 / 8 |
| 5 | **D2 shift 1%** | 82 / 9 / 10 | 76 / 12 / 12 | 82 / 8 / 9 |
| 20 | D0 current | 79 / 15 / 6 | 74 / 18 / 7 | 78 / 17 / 5 |
| 20 | D1 no drift | 80 / 13 / 7 | 75 / 18 / 7 | 82 / 12 / 6 |
| 20 | **D2 shift 3%** | 82 / 9 / 9 | 77 / 12 / 11 | 83 / 10 / 8 |

## Year by year (checked after the verdict, not part of it)
D2 brought below and above closer in 12 of 13 years (2016 overshot: 6% below, 16% above at h = 20) and coverage
rose or held in most. Falling years are still poor: 2018 75%, 2024 66–67% (from 62–66%), misses still mostly low.

## Why D1 failed
The skew is not the share's past trend carried forward. Future moves simply land lower than the share's own past
moves suggest, about 1% a week and 3% a month on average across DSE stocks, consistent with a long weak market.

## Change made
`dse_quant.watch.SKEW_SHIFT = {5: 0.01, 20: 0.03}`, applied in `forecast()` to the low, middle and high (after any
volume widening). The page text now gives the shifted track record.

## Caveats
- One fixed shift for every share and every market. If DSE turns into a long rising market, the shift may make
  misses lean high; re-run `scripts/range_skew.py` yearly and keep the pre-registered rules.
- The volume widening (×1.3 on 2x+ turnover days) was tested on the unshifted range; the shift moves all three
  points equally, so the widening's width is unchanged, but the two were not tested together.
