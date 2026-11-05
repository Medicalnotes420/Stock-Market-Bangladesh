---
name: stock
description: Full fundamental and technical analysis of one DSE share, like an investing.com share page. Use for "/stock CODE", "analyse CODE", "tell me about <DSE share>", "is CODE fundamentally strong".
argument-hint: <DSE trading code, e.g. AL-HAJTEX>
---

Analyse the DSE share `$ARGUMENTS` (a trading code such as `AL-HAJTEX`; upper-case it; if none was given, ask for one).

1. Hand the work to the **dse-watch** agent with this prompt: "Full analysis of <CODE>: run the one-off check and
   follow your 'Full analysis of one share' section." It runs
   `python scripts/watch_share.py --symbols <CODE> --out data/watch/one_off.html` (prices from stocknow.com.bd,
   fundamentals and news from dse.com.bd; no login needed) and reads the page.
2. Relay its reply to the user as it is (Price, Fundamentals, Technicals, Outlook, News and dates), problems first.
3. Show the full page: open `data/watch/one_off.html` in the browser pane.

Not investment advice: never say buy, sell or hold. If the code is wrong the script prints
"no data from stocknow (check the trading code)"; say so and stop.
