# Deposit rates and the share index: results

Run 2026-11-05 as pre-registered in docs/DEPOSIT_RATES_PREREG.md (`python -W ignore scripts/deposit_rates.py`,
output results/deposit_rates.csv). Deposit rate = IMF series (tracks the fixed-deposit rate, 1990–2026).

## Answer in one line
**Yes, an association very likely exists, but it is modest and mostly the general interest-rate cycle.**
When deposit rates rise, shares do worse, at the same time and over the following 6 months. It pointed the
same way in every cut, but no single test cleared the strict bar (p < 0.0125), so the formal verdict is
**WEAK** for both "move together" and "predicts".

## The four main tests (bar: p < 0.0125)
| Test | Result | p |
|---|---|---|
| P1 Same year, 1998–2025 | −0.41 | 0.030 |
| P2 Last year's change → this year | −0.00 | 0.99 (nothing) |
| P3 Same 6 months, 2012–2026 (every start negative) | −0.38 | 0.058 |
| P4 Past 6 months → next 6 months (every start negative) | −0.45 | 0.025 |

In years deposit rates rose, shares averaged +0.8% (median −9.8%, 16 years); in years they fell or held,
+22.4% (median +19.4%, 12 years).

## Checks
| Check | Result | Reading |
|---|---|---|
| Both eras, same year | 1998–2011 −0.22; 2012–2025 −0.57 | Same direction in both, stronger recently |
| Without floor-price windows (P4) | −0.42, p 0.07, every start negative | Not a floor-price artefact |
| Without 2020–21, the rate caps and big rally (P4) | −0.40, p 0.07 | Not just one episode |
| Reverse: shares → later deposit rates | +0.03 | Shares don't move rates; the order is rates first |
| Deposit rate beyond the bond yield | −0.26, p 0.24 (both P3 and P4) | Little extra: it's the overall rate level |
| Real deposit rate (after inflation) → next year | +0.11 | No link |
| Deposit vs bond yield, monthly levels | 0.86 | They move almost together |

## What it means
- **The association is real in direction and survives every robustness cut**: both eras, without the
  floor price, without the 2020–21 caps. Rates move first; shares follow, over months, not a year later.
- **It is not specific to deposits.** Take out what the bond yield already explains and most of it goes. So the
  driver is the interest-rate cycle (Bangladesh Bank policy, liquidity), which deposits, bonds and lending all
  follow. A likely channel: when fixed deposits and savings certificates pay 9–10% safely, money leaves shares.
- **It is not a timing rule.** Too few independent rate cycles to pass a strict test, the effect is modest
  (correlation around −0.4), and last year's rate change says nothing about this year.
- **Practical use:** rising deposit and bond rates are a sensible caution flag for DSEX, alongside the watch
  page. Not a buy or sell signal. The yearly rates check (each 1 August) will show if newer months agree.
