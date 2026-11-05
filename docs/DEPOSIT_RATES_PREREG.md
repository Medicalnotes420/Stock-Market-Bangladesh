# Deposit rates and the share index (pre-registration)

Fixed on 2026-11-05, before this analysis was run. Question from the user: is there an association between
bank deposit rates and DSEX, or not?

**Already seen (so not a clean test):** a quick look found that in years when deposit rates rose, shares
averaged +2.4% vs +22.4% (same-year rank correlation −0.37, p 0.07, 1998–2023), and a 6-month lead with median
p 0.09 (2012–2023). The rules below are fixed now; they guard against picking the best-looking cut afterwards.

## Data
- **Deposit rate:** IMF MFS_IR "Deposit Rate" for Bangladesh, monthly, Jan 1990 – Jun 2026
  (`data/raw/imf/MFS_IR_BGD.xml`). It is not Bangladesh Bank's weighted average deposit rate (6.2–6.4% in
  2025–26, bb.org.bd, while the IMF series shows ~9%); it tracks the fixed-deposit rate (~6% under the
  April 2020 deposit cap, ~9% in 2024–25). Bangladesh Bank's longer history sits behind a CAPTCHA; not used.
- **Shares:** yearly taka index return 1997–2025 (`results/dse_long_run.csv`); DSEX month-end, Oct 2012 on.
- **Controls:** government bond yield (IMF, monthly from Aug 2006); inflation (World Bank, yearly).

## Primary tests (4; Bonferroni: p < 0.0125, two-sided, 10,000 seeded shuffles)
| Id | Question | Measure |
|---|---|---|
| P1 | Move together, yearly | Spearman: change in the yearly-average deposit rate in year t vs share return in year t, 1998–2025 |
| P2 | Lead, yearly | change in year t−1 vs share return in year t, 1999–2025 |
| P3 | Move together, 6 months | change in deposit rate over 6 months vs DSEX change over the same 6 months; non-overlapping, every start month; median p |
| P4 | Lead, 6 months | change over the past 6 months vs DSEX over the next 6 months; non-overlapping, every start month; median p |

## Verdict
- **ASSOCIATION EXISTS (move together)** if P1 or P3 is negative with p < 0.0125, and P1's correlation is
  negative in both 1998–2011 and 2012–2025.
- **PREDICTS** if P2 or P4 is negative with p < 0.0125 (P4: every start negative), and the same holds without
  the floor-price windows.
- **WEAK** for either kind if negative with p < 0.05 but not 0.0125.
- **NONE** otherwise.

## Secondary checks (reported, not part of the verdict)
1. Real deposit rate (deposit − inflation) at the end of year t−1 vs share return in year t.
2. Reverse direction: DSEX over the past 6 months vs the deposit-rate change over the next 6.
3. Does the deposit rate add anything beyond the bond yield? P3/P4 using the part of the deposit-rate
   change not explained by the bond-yield change (least-squares residual), Oct 2012 on.
4. Without 2020–21 (the deposit/lending caps and the big rally).
5. Without floor-price windows (2020-03-19 to 2021-04-07, 2022-07-28 to 2024-01-21).

## Known limits
- ~28 yearly values; ~22 per 6-month start. Only a fairly strong link can pass.
- Rates in Bangladesh were capped by policy (9% lending, 6% deposit from April 2020), so some moves are
  decisions, not market rates.
- Association is not cause: rates, inflation, liquidity and policy move together.
