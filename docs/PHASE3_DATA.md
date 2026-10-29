# Phase 3 — Data Pipeline

Status: DRAFT for approval · 2026-10-29

## Sources (Option A, approved by you)
| Id | Dataset | Licence | Local path (git-ignored) |
|---|---|---|---|
| A1 | Sunny, Nafis, Khan (2025). *Dhaka Stock Exchange Historical Data (1999-2025)*. Mendeley Data, v1. doi:10.17632/5mww8rb9td.1 | CC BY 4.0 | `data/raw/a1/` (77 MB CSV) |
| A2 | Muhammad, Islam, Alam (2026). *Dhaka Stock Exchange End-of-Day Financial Dataset with Coverage Metadata*. Mendeley Data, v4. doi:10.17632/23553sm4tn.4 | CC BY 4.0 (the licence notes third-party content may need further permission; A2 credits Amarstock as a source) | `data/raw/a2/` (59 MB zip) |

CC BY attribution: both datasets were changed by this pipeline (A1 dates repaired, rows quarantined, prices re-adjusted). Licence: https://creativecommons.org/licenses/by/4.0/

## What the raw data looked like (scripts/profile_raw.py, profile_raw2.py)
| Finding | Number |
|---|---|
| A1 duplicate (ticker, date) rows | 68,739 |
| A1 rows whose prices contradict each other (high < low, close outside high–low, etc.) | 22,445 |
| A1 vs A2 close mismatch >0.5% on overlapping rows | 17.4% (2012–2021); 0% from 2023 |
| …of those, rows that match after swapping day and month | 148,124 of 151,997 with day ≤ 12 |
| A1 tickers that stop trading 2013–2024 / of those present in A2 | 44 / 2 → **A2 is survivorship-biased** |
| A2 adjusted series: factor steps that revert (GP 1.0→0.85→1.0; BRACBANK reverses after 3 days) | many → **A2 adjustments not trusted** |
| A2 DSEX "volume" field changes units around 2018 (median Tk 2.7–8 crore/day before, Tk 400–1,400 crore after) | → turnover recomputed from stocks |

## Pipeline (scripts/build_clean.py → data/clean/)
1. **A2 unadjusted is the main source.** It covers 2012-10-01 to 2026-01-22.
2. **A1 date repair** (`data/load.repair_a1_dates`). For each ambiguous A1 date, the stocks that also appear in A2 vote on the correct date, and the whole day's block moves to the winner. Unresolved dates and anything before Oct 2012 are dropped.
   - 827 dates were swapped back.
   - 1,780 rows were dropped as unresolved.
   - 439,198 rows from before Oct 2012 were dropped.
   - 4,825 duplicate rows with conflicting prices were dropped.
   - **Mismatch after repair: 0.72%** of 935,179 overlapping rows, down from 17.4%.
3. **Dead tickers** come from the repaired A1: 55 tickers, 36 of them guessed to be equities by name pattern. The full list is in `report.json` for you to review.
4. **Quarantine** (`quarantine.csv`): 8,116 rows with contradictory prices are removed (7,033 from A1, 1,083 from A2).
5. **Corporate actions** (`data/adjust.py`): an action is accepted only when A2's adjustment factor steps by more than 1% and holds for 10 sessions, **and** the raw price falls that day. 1,556 actions were accepted. Prices are back-adjusted. Traded value and `close_raw` stay unadjusted.
6. **Unexplained gaps:** 1,648 rows across 408 tickers moved beyond the daily limit with no accepted action. They are kept in the data, flagged with `gap_flag`, and listed in the quarantine file.
7. **Lock flags** (`limits.lock_flags`): `lower_lock` and `upper_lock` mark days that closed within one tick of the limit.
8. **Market file** (`market.csv`): DSEX close, turnover (sum of equity traded value), advancers, decliners and stock count for each date.

## Output
| Item | Value |
|---|---|
| Rows / tickers | 1,123,656 / 532 |
| Dates | 2012-10-01 … 2026-01-22 |
| Universe size at year-end (Tk 2 crore median value, ≥250 sessions, price ≥ Tk10) | 2013: 38, 2014: 49, 2015: 27, 2016: 76, 2017: 63, 2018: 42, 2019: 31, 2020: 76, 2021: 79, 2022: 42, 2023: 39, 2024: 32, 2025: 43 |
| DSEX dates present / missing | 2,832 / 340 (≈70 per year missing in 2023–2025) |

Rebuild: `python scripts/build_clean.py` (~1m45s). Tests: `python -m unittest discover -s tests -t .` gives **53 tests OK**.

## Known gaps (these feed the Phase 4 bear case)
1. **No point-in-time category (A/B/N/Z), suspension or SME-board history.** The junk filter in spec §4 is not enforced. Backtests will include stocks that were in Z category at the time.
2. **Cash dividends are not adjusted.** Returns are price-only, which biases C4 (low-vol dividend tilt) and C5 (dividend drift) against themselves.
3. **1,522 unexplained equity gaps.** About 60% are up-moves. They cluster in 2012 (214), 2020 (271, the COVID reopening and floor-price period) and 2024–25 (295). My guess is that the historical limit rules differed from today's tiers. Not verified. Proposal for Phase 4: exclude a stock for 20 sessions after an unexplained gap, and report results with and without that rule.
4. **DSEX is missing on 340 dates.** The regime filter needs an index every day. Proposal for Phase 4: build an index from the stocks themselves, use it to cross-check DSEX on days both exist, and use it to fill missing days. It will be clearly labelled as a proxy.
5. **Traded value = close × volume,** computed from the vendor's volume. The two sources disagree on volume for 18.9% of overlapping rows. Liquidity filters could be off by that much.
6. **The data ends in Jan 2026.** Paper trading (Phase 5) needs an approved daily source: DSE day-end pages for personal use, or StockNow if they give written consent.
7. **Dead tickers' instrument types are guessed from their names,** and their history is only as good as the date-repair vote.
