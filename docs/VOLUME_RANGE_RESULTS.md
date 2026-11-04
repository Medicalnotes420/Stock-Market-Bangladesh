# Widening the price range on high-volume days: results

Run 2026-11-05 as pre-registered in docs/VOLUME_RANGE_PREREG.md (`python -W ignore scripts/volume_range.py`,
output results/volume_range.csv). R = traded value today / its prior 20-session average.

## Coverage of the "80%" range by volume (h = 5; h = 20 is similar)
| R | 2014–22 (A) | 2023–Jan 26 (B) | 2026 (C) |
|---|---|---|---|
| < 0.5 | 85% | 81% | 83% |
| 0.5–1 | 81% | 77% | 82% |
| 1–2 | 77% | 72% | 80% |
| ≥ 2 | 70% | 67% | 74% |
| ≥ 2, widened ×1.3 | 81% | 76% | 84% |

k = 1.3 was fitted on A only, for both h. h = 20 widened: 81% / 77% / 84%.
**Verdict: ADOPT for h = 5 and h = 20** (all three pre-registered conditions hold).

## Independent checks (three read-only reviewers, none refuted it)
- **Code:** no look-ahead, forward window and gap filter correct, arrays aligned, k fitted on A only.
- **Statistics:** reproduced exactly. Not just high-volatility stocks: within every volatility quintile, high-volume
  days had lower coverage, and a volatility-only rule did worse in B (72%). But the pass in B is thin: a date-block
  bootstrap puts B at 76% [73–79%] (h = 5) and 77% [73–81%] (h = 20), about a 1-in-5 chance it is really below 75%.
  2024 failed badly even widened (66–67%); 2023 and 2025 offset it. Thresholds 1.5x and 3x point the same way.
- **Live page:** rebuilt the way `watch.forecast` works (own rows, no gap filter, 60-move minimum, share volume);
  still k = 1.3 and coverage 81/78/85% (h = 5), 82/78/82% (h = 20).

## Caveats for the page change
- Use close × volume for R (as the test and the #38 filter do). Share volume misses ~10% of high-value days, the
  worst-covered ones.
- k = 1.3 is untested for shares with under 125 past moves (new listings).
- The widening is symmetric; misses stay mostly below the range (h = 20, B: 16% below vs 8% above).
- In a falling year like 2024, even the widened range covers only about two thirds.
