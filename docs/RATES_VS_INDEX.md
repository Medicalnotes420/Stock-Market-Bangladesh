# Government bond yields vs the stock index

Run 2026-11-05 (`python -W ignore scripts/rates_vs_index.py`, output results/rates_monthly.csv,
results/rates_yearly.csv). Descriptive comparison, not a pre-registered test.

Data: IMF Monetary and Financial Statistics, Bangladesh, monthly: government bond yield (Aug 2006 – Jun 2026),
treasury bill yield, repo (policy) rate. Share index: World Bank yearly taka return (S&P Bangladesh, 2006–2012)
and DSEX (2013 on), prices only. The IMF's recent lending and deposit rates look mislabelled (lending below
deposit), so they are not used.

## Answer in one line
Since 2006, government bonds have done about as well as shares with dividends, at far less risk; since 2011
they have done much better. Rising bond yields tended to come before weaker DSEX, but that is an observation,
not a tested forecast.

## Tk 100 put in each, at the start of the year
| From | Years | Government bonds | Shares, prices only | + 3% a year dividends | + 4% a year |
|---|---|---|---|---|---|
| 2006 | 20 | Tk 631 | Tk 338 | Tk 611 | Tk 741 |
| 2011 | 15 | Tk 373 | Tk 61 | Tk 96 | Tk 111 |

Bonds beat the share index's price change in 11 of 20 years. The 2006 start includes the 2007 bubble
(+126%); from 2011 shares never caught up. Bonds are grown at each year's average yield, a rough stand-in for
rolling into new bonds; dividends are an assumed range (no dividend data in this project).

## Yields over time
Bond yields fell from ~12% (2006–08, 2012–14) to 6–7% (2016–17, 2021), then rose to 12.4% in 2024 and were
10.2% in June 2026 (T-bill 9.8%, repo 10.0%). The low-rate years 2020–21 match DSEX's big rally; the climb
in 2023–24 matches the fall after the floor price was lifted.

## How they move together (monthly, Nov 2012 – Jun 2026)
- Same month: DSEX change vs bond yield change, correlation −0.15 (weak).
- Bond yield change over the past 6 / 12 months vs DSEX over the next 6 / 12 months: −0.33 / −0.41. Rising
  yields tended to come before weaker shares. Windows overlap, so there are only a handful of independent
  cases (in effect two rate cycles); not tested, so it is not a forecast rule.
- Yield level vs DSEX next 12 months: −0.15.

## Caveats
- A bond yield is what new bonds paid that year; a holder of older bonds also sees price changes.
- Taka returns before 2013 are converted from dollars with the yearly average rate.
- Floor prices (2020–21, 2022–24) held DSEX up, which flatters shares in those years.
