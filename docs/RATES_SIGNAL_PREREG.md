# Do rising bond yields come before weaker DSEX? (pre-registration)

Fixed on 2026-11-05, before the test was run. docs/RATES_VS_INDEX.md saw a correlation of about −0.33 (6 months)
and −0.41 (12 months) between the past change in the government bond yield and DSEX's next change, using
overlapping windows. This test fixes the method in advance and removes the overlap.

**Important:** the data below has already been looked at once (that is how the idea came up). So the best this
test can say is that the link holds in-sample with a sound method. Only months after June 2026 are fresh; a
forward record starts here.

## Data
- Government bond yield, monthly average (IMF MFS_IR, `results/rates_monthly.csv`).
- DSEX, last close of each month (`data/clean/market.csv`).
- Months from Oct 2012 to the last month where both the bond yield and the outcome exist.

## Measure
At the end of month t: **signal** = bond yield(t) − bond yield(t−h); **outcome** = DSEX(t+h) / DSEX(t) − 1.
h = 6 (primary) and h = 12 (check).

## Non-overlapping samples
Use only every h-th month, so no two outcomes overlap. Because the starting month is arbitrary, do it for
every possible start (6 starts for h = 6, 12 for h = 12) and report all.

## Statistics
For each start: Spearman correlation of signal vs outcome; p-value from 10,000 seeded shuffles (two-sided).
Also the mean outcome when the signal is > 0 vs ≤ 0.

## Verdict
- **HOLDS IN-SAMPLE** if, for h = 6: the correlation is negative for **every** start and the **median** p
  across starts is < 0.05; **and** for h = 12 the median correlation is negative; **and** with h = 6 the
  median correlation is negative in both halves (months up to Dec 2019, and from Jan 2020).
- **WEAK** if every h = 6 start is negative but the median p ≥ 0.05.
- **NO** otherwise.

Sensitivity, reported but not part of the verdict: dropping samples whose outcome window is mostly within a
floor-price period (2020-03-19 to 2021-04-07, 2022-07-28 to 2024-01-21).

## Known limits
- About 26 independent 6-month samples, 13 for 12 months. Only a strong link can pass.
- In-sample only (see above). Even HOLDS IN-SAMPLE is not a forecast until fresh months agree.
- The IMF bond yield is a monthly average, so it is known only at month end; the outcome starts there.
