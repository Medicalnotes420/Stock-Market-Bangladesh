# Learnings from "Hm Shamim's My Secret Series" (Word file, ~114 tips)

Source: `My secret.docx`, read in full on 2026-10-29. The PDF version could not be read: rendering it needs poppler, a new dependency (not installed, so I'm asking first).

How to read this: the author claims "90% success" for many rules. None of that has been measured. This system's job is to test such claims before trusting them, so each tip is sorted by what can actually be done with it here.

## A. Testable rules on daily data (can be backtested now)
| # | Rule (author's words, condensed) | Type | Holding |
|---|---|---|---|
| 1, 13 | RSI rises to 90+; wait for the pullback to ~70, buy; sell at T+2 | entry | 2–3 days |
| 7, 32 | Turnover surges (day value ≫ average) with price +3–4%, after ~15 days of flat price and turnover | entry | T+2 to T+5, author expects 5–10% |
| 23 | At support, price flat but Money Flow (MFI) rising | entry | T+6/7, author expects 10–15% |
| 25, 30 | Bollinger squeeze (bands narrowing), price within 2–3% for 15 days, SMAs flat mid-band, MFI 60–70 and rising | entry | T+6/7, author expects 5–10% |
| 27 | In a trending market: after a 10–25% rise, 5–6 days going sideways, buy | entry | swing |
| 22 | After a 50–100% fall, 10–15 days going sideways, buy | entry | mid-term |
| 67 | SMA(13) crosses above SMA(19) (the author's screener) | entry | swing |
| 96 | SMA cross up with price close to the SMA (not 10–20% above); ADX +DI up, −DI down; MFI > 60 | entry | swing |
| 98 | "Lazy" stocks stuck in a 10–12% range all year: buy near the bottom, sell near the top, ~3 times a year | entry/exit | ~4 months |
| 2 | MACD line falls and touches the signal line from above: sell | exit | — |
| 3 | Any moving average turns from bullish to bearish: sell | exit | — |
| 21 | Hold while Aroon Up stays ≥ 90; sell below that | exit | — |
| 31 | Close is far outside the upper Bollinger band and RSI > 75: sell half (the author sells all) | exit | — |
| 39 | In a strong trend, sell when RSI reaches 97 | exit | — |
| 20 | Set the sell target 5–10% below resistance | exit | — |
| 38 | Technical signals fail when turnover is 90–95% below normal; trust them only when turnover is ≥ 40–50% of its 2–3 month average | filter | — |
| 62, 64 | After a big-volume high day ("top side flash"), the next 2 days don't trade above that high; often recovers from day 3 | check of the author's claim | — |
| 49 | A rebound after a fall usually retraces only 50–60% of the drop | check of the author's claim | — |
| 59 | Corrections end around 45/90/135/180/360 days (Gann) | check of the author's claim | — |
| 6 | Some price levels do very well during Ramadan, with buying 3–4 months earlier | seasonal | needs verified Ramadan dates |

## B. Already in the system
- **29, 53:** keep a watchlist of 4–5 stocks and study them for months. This exists: `watchlist.txt` and the status page.
- **90, 107:** don't keep changing strategy; commit to one plan. This matches pre-registration.
- **95, 99, 107:** don't chase the top-10 list or news and Facebook tips. The system never uses them.
- **65, 99, 104:** take at least a week before big decisions, and don't decide from one hour or one day. The system works on end-of-day data only, with no intraday decisions.

## C. Not testable with this data
- **Screen reading** (26, 35–37, 39–43, 46, 58, 91, 93, plus the "soft dismissal" and "fake confirmation" sections): judging single big trades, halts and minute charts. This needs trade-by-trade (tick) data, which we don't have.
- **Category moves** (10, 19, 79): buying B/N stocks before they move to A; A→Z means an immediate 20–30% loss. There's no category history in the data.
- **Fewer total shares → bigger gains** (8): there's no shares-outstanding data.
- **Dividend-driven** (10, 18): build before the dividend, sell on the declaration. There are no dividend or declaration dates.
- **Order tactics** (9, 15, 29 "magic numbers" such as selling at 19 or 49 rather than 20 or 50): these need fills inside the day.
- **Market-maker narratives** (5, 72, 78, 82, 84, 85, 111, 114): stories about other traders' intent. They make no rule that can be checked.

## D. Conflicts with your Phase 1 risk limits (not implemented without your decision)
- **"Single script" strategy** (69, 76, 95, 97, 99–105): put the whole portfolio in 1–2 stocks; the author argues money management is for big funds only.
  - **The conflict:** your spec caps a position at 10% of the portfolio and 5% of daily turnover, enforced in code where nothing can override it.
  - **The data:** the Phase 4 results show single-stock drawdowns of 30–43% even in the low-volatility strategy.
- **Spreading one holding across ≈10 accounts** (5) to stay unseen by "gamblers": that's account structuring, outside this system's scope, and not something I'll build.

## E. Mindset (kept as notes)
These are attitude points rather than rules, kept for reference:
- Think in percentages, not taka amounts (47, 100, 101).
- Ignore the noise (73).
- 95% of traders lose, so think differently from the crowd (71, 102).
- Avoid margin loans (76, 107).
- Don't spread small money thin (51, 69).
- Big gain means big pain (54).
