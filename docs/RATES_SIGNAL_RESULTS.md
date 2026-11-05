# Do rising bond yields come before weaker DSEX? Results

Run 2026-11-05 as pre-registered in docs/RATES_SIGNAL_PREREG.md (`python -W ignore scripts/rates_signal.py`,
output results/rates_signal.csv). In-sample only: this data had been looked at once before the test.

## Answer in one line
**WEAK.** The direction is consistent (rising yields, weaker DSEX) in every non-overlapping slice, but it
falls just short of the bar and comes mostly from 2020 onward. Not a forecast rule.

## Results
| | Result | Bar |
|---|---|---|
| 6 months, every start month negative | yes, 6 of 6 (−0.24 to −0.58) | required |
| 6 months, median p | 0.063 | < 0.05: **missed** |
| 12 months, median correlation | −0.49 (p 0.16) | < 0: met |
| Halves, 6 months | to 2019 −0.15; from 2020 −0.79 | both < 0: met, but the first is faint |
| Leaving out floor-price windows | −0.33, p 0.20 | (sensitivity only) |

After a 6-month rise in the bond yield, DSEX averaged −0.3% over the next 6 months, against +5.9% when the
yield had not risen (all months, overlapping, so these overstate certainty).

## What it means
- Rates matter in the direction you'd expect: when bond yields have been rising, shares have done worse.
- The evidence is mostly one rate cycle: very low yields in 2020–21 (DSEX's big rally) and the climb in
  2023–24 (its fall). Before 2020 the link was faint, and the floor-price years blur it.
- So: useful context next to the watch page, not a signal to act on. Re-run each year; if the link keeps
  showing in months after June 2026 (fresh data), it becomes much more believable.
