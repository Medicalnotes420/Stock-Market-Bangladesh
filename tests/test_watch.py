import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from dse_quant.watch import (SKEW_SHIFT, adjust_for_dividend, analyze, data_warnings, forecast, fundamentals, load_csv,
                             log_forecasts, parse_company, parse_news, rates_status, render, score_forecasts, tech_summary,
                             upcoming_dividend)


def frame(closes):
    idx = pd.bdate_range("2025-01-01", periods=len(closes))
    c = pd.Series(closes, idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c + .5, "low": c - .5, "close": c, "volume": 1000.0})


def write(df, path, headers):
    out = df.reset_index().rename(columns={"index": "date"})
    out.columns = headers
    out.to_csv(path, index=False)


class Watch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_load_csv_aliases(self):
        p = self.tmp / "a.csv"
        write(frame(np.linspace(10, 20, 40)), p, ["Date", "Open Price", "HIGH", "low", "Closing Price", "Volume"])
        df = load_csv(p)
        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(len(df), 40)
        self.assertAlmostEqual(df.close.iloc[-1], 20.0)

    def test_missing_close_named(self):
        p = self.tmp / "b.csv"
        frame(np.ones(40)).drop(columns="close").reset_index(names="Date").to_csv(p, index=False)
        with self.assertRaisesRegex(ValueError, "close"):
            load_csv(p)

    def test_bad_value_rejected(self):
        p = self.tmp / "c.csv"
        df = frame(np.linspace(10, 20, 40)).astype(object)
        df.iloc[5, 3] = "abc"
        write(df, p, ["Date", "Open", "High", "Low", "Close", "Volume"])
        with self.assertRaisesRegex(ValueError, "row 7"):
            load_csv(p)

    def test_uptrend_and_sma20_cross_fires_on_cross_bar(self):
        closes = list(np.full(60, 10.0)) + [9.0] * 20 + [12.0]  # below SMA20, then jumps above on the last bar
        a = analyze(frame(closes))
        fired = {x["rule"] for x in a["alerts"] if x["fired"]}
        self.assertIn("Close crosses above SMA20", fired)
        self.assertNotIn("Close crosses above SMA20", {x["rule"] for x in analyze(frame(closes[:-1]))["alerts"]
                                                       if x["fired"]})
        self.assertEqual(analyze(frame(np.linspace(10, 30, 80)))["trend"], "up")
        self.assertEqual(analyze(frame(np.linspace(30, 10, 80)))["trend"], "down")

    def test_rsi_and_level_alerts(self):
        a = analyze(frame(np.linspace(10, 30, 80)), above=25, below=5)
        fired = {x["rule"] for x in a["alerts"] if x["fired"]}
        self.assertIn("RSI(14) above 70 (overbought)", fired)
        self.assertIn("Close above 25.00", fired)
        self.assertNotIn("Close below 5.00", fired)
        self.assertAlmostEqual(a["change"]["1d"], 30 / np.linspace(10, 30, 80)[-2] - 1)

    def test_secret_flags_carry_backtest_verdict(self):
        s = analyze(frame(np.linspace(10, 30, 80)))["secrets"]  # steady rise: RSI pinned near 100
        rsi_flag = [x for x in s if x["flag"].startswith("#39")]
        self.assertEqual(len(rsi_flag), 1)
        self.assertIn("7 cases", rsi_flag[0]["verdict"])
        self.assertTrue(all(x["verdict"] for x in s))

    def test_forecast_range(self):
        rng = np.random.default_rng(0)
        closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
        f = analyze(frame(closes))["forecast"]
        self.assertEqual(set(f), {5, 20})
        for h in (5, 20):
            self.assertLess(f[h]["low"], f[h]["mid"])
            self.assertLess(f[h]["mid"], f[h]["high"])
        self.assertGreater(f[20]["high"] - f[20]["low"], f[5]["high"] - f[5]["low"])  # wider further out
        self.assertEqual(analyze(frame(np.linspace(10, 20, 40)))["forecast"], {})  # too little history

    def test_forecast_shifted_down(self):
        closes = pd.Series(np.full(300, 50.0))
        f = forecast(closes)  # flat history: every past move is 0, so the range collapses onto the shift
        for h, s in SKEW_SHIFT.items():
            for k in ("low", "mid", "high"):
                self.assertAlmostEqual(f[h][k], 50 * np.exp(-s))

    def test_volume_vs_20day_average(self):
        df = frame(np.linspace(10, 30, 80))
        df.loc[df.index[-1], "volume"] = 3000.0  # spike today; the 20 sessions before it are 1000
        a = analyze(df)
        self.assertEqual((a["volume"], a["vol_avg20"]), (3000.0, 1000.0))
        self.assertIn("(3.0x)", Path(render({"X": a}, self.tmp / "v.html")).read_text(encoding="utf-8"))

    def test_range_widened_on_high_turnover(self):
        rng = np.random.default_rng(0)
        df = frame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))))
        plain = analyze(df)
        self.assertNotIn("Widened", Path(render({"X": plain}, self.tmp / "p.html")).read_text(encoding="utf-8"))
        df.loc[df.index[-1], "volume"] = 3000.0  # turnover ~3x the prior 20 sessions
        a = analyze(df)
        for h in (5, 20):
            p, w = plain["forecast"][h], a["forecast"][h]
            self.assertAlmostEqual(w["mid"], p["mid"])
            self.assertAlmostEqual(np.log(w["high"] / w["mid"]), 1.3 * np.log(p["high"] / p["mid"]))
            self.assertAlmostEqual(np.log(w["mid"] / w["low"]), 1.3 * np.log(p["mid"] / p["low"]))
        self.assertIn("Widened", Path(render({"X": a}, self.tmp / "w.html")).read_text(encoding="utf-8"))

    def test_render_escapes_and_has_disclaimer(self):
        out = render({"<script>x</script>": analyze(frame(np.linspace(10, 30, 80)))}, self.tmp / "w.html",
                     note="<b>n</b>", errors=["<img src=x>"])
        html = Path(out).read_text(encoding="utf-8")
        self.assertIn("<svg", html)
        self.assertIn("Not investment advice", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)

    def test_news_parsed_from_page_payload_and_rendered(self):
        import json
        items = [{"id": "2", "type": "Dividend", "date": "27 Oct 2026", "summary": "Dividend <Declaration>",
                  "body": 'Board recommended 22.50% "cash"'},
                 {"id": "1", "type": "Financials", "date": "13 Nov 2025", "summary": "Q1 Financials", "body": "$13"}]
        chunk = json.dumps('5:["$","div",null,{"news":' + json.dumps(items, separators=(",", ":")) + '}]\n')  # compact, as the site sends
        page = f'<script>self.__next_f.push([1,{chunk}])</script>'
        got = parse_news(page)
        self.assertEqual([x["summary"] for x in got], ["Dividend <Declaration>", "Q1 Financials"])
        self.assertEqual(got[1]["body"], "")  # payload reference dropped, summary kept
        self.assertEqual(parse_news("<html></html>"), [])
        a = analyze(frame(np.linspace(10, 20, 80)))
        with tempfile.TemporaryDirectory() as d:
            a["news"] = got
            html = Path(render({"X": a}, Path(d) / "w.html")).read_text(encoding="utf-8")
            self.assertIn("Company news", html)
            self.assertIn("Dividend &lt;Declaration&gt;", html)
            a["news"] = "news fetch failed: timeout"
            self.assertIn("news fetch failed", Path(render({"X": a}, Path(d) / "w.html")).read_text(encoding="utf-8"))

    def test_company_record_parsed_and_fundamentals(self):
        import json
        co = {"code": "X", "name": "X <Ltd>", "sector": "Textile", "category": "B", "marketCap": 1.5e9,
              "faceValue": 10, "paidUpCapital": 2e8, "freeFloat": 60.0, "authorizedCapital": 500,
              "reserveWithoutOci": 100.0, "loanStatus": {"shortTerm": 20.0, "longTerm": 180.0},
              "creditRating": "$undefined", "asOfDate": "2026-11-05", "yearEnd": "June",
              "multiYearFinancials": [{"year": 2024, "epsBasic": 4.0, "nav": 20.0, "profit": 80, "pe": 12},
                                      {"year": 2025, "epsBasic": 2.0, "nav": 25.0, "profit": 40, "pe": None}],
              "interimFinancials": {"periodEnds": {"q1": "202509", "annual": "202606"},
                                    "rows": [{"metric": "Earnings Per Share (EPS) Basic", "q1": 1.0, "annual": 5.0},
                                             {"metric": "EPS Diluted*", "q1": None, "annual": None}]},
              "dividendHistory": [{"year": 2024, "cash": 10, "stock": 0}, {"year": 2025, "cash": 20, "stock": 5}],
              "sharePattern": [{"date": "Oct 31, 2026", "pattern": {"sponsor": 30.0, "public": 70.0}}]}
        chunk = json.dumps('5:["$","div",null,{"company":' + json.dumps(co, separators=(",", ":")) + '}]\n')
        got = parse_company(f'<script>self.__next_f.push([1,{chunk}])</script>')
        self.assertEqual(got["code"], "X")
        self.assertIsNone(parse_company("<html></html>"))
        f = fundamentals(got, 50.0)
        self.assertEqual(f["eps"], 5.0)  # interim annual (FY to 06/2026) is newer than the FY2025 row
        self.assertIn("2026", f["eps_when"])
        self.assertAlmostEqual(f["pe"], 10.0)
        self.assertAlmostEqual(f["pb"], 2.0)  # NAV from the newest multi-year row
        self.assertAlmostEqual(f["div_tk"], 2.0)  # 20% of Tk 10 face
        self.assertAlmostEqual(f["div_yield"], 0.04)
        self.assertAlmostEqual(f["debt_equity"], 200 / (25 * 2e7 / 1e6))
        self.assertEqual(f["years"][-1]["div"], "20% cash + 5% stock")
        self.assertEqual(len(f["interim"]["rows"]), 1)  # all-empty diluted row dropped
        news = [{"type": "Notice", "body": "recommended 99% cash dividend for the year ended June 30, 2027"},
                {"type": "Dividend", "body": "The Board has recommended 10% Cash and 5% Stock Dividend for the year "
                 "ended June 30, 2026. Reported EPS of Tk. (2.85), NAV per share of Tk. 12.50 and NOCFPS ..."}]
        d = fundamentals(got, 50.0, news)  # Notice ignored; the FY2026 declaration beats the FY2025 rows
        self.assertEqual((d["div_cash_pct"], d["div_stock_pct"], d["nav"]), (10.0, 5.0, 12.5))
        self.assertIn("2026", d["nav_when"])
        self.assertAlmostEqual(d["div_yield"], 1.0 / 50)
        neg = fundamentals(got, 50.0, [{"type": "Dividend", "body": "recommended No Dividend for the year ended "
                                        "June 30, 2026. NAV per share of Tk. (3.10)"}])
        self.assertEqual((neg["div_cash_pct"], neg["nav"], neg["pb"]), (0.0, -3.1, None))
        old = fundamentals(got, 50.0, [{"type": "Dividend", "body": "recommended 1% cash dividend for the year "
                                        "ended June 30, 2025. NAV per share of Tk. 1.00"}])
        self.assertEqual(old["nav"], 25.0)  # not newer than the table: ignored
        for k in ("multiYearFinancials", "interimFinancials", "dividendHistory", "sharePattern", "loanStatus"):
            fundamentals({**got, k: "$undefined"}, 50.0)  # DSE's missing-value marker must not crash
        fundamentals({**got, "interimFinancials": {"periodEnds": "$undefined", "rows": "$undefined"}}, 50.0)
        loss = fundamentals({**got, "interimFinancials": {}}, 50.0)
        self.assertEqual(loss["eps"], 2.0)
        self.assertIsNone(fundamentals({**got, "multiYearFinancials": [{"year": 2025, "epsBasic": -1.0, "nav": 9}],
                                        "interimFinancials": {}}, 50.0)["pe"])
        a = analyze(frame(np.linspace(10, 20, 80)))
        a["fund"] = f
        html = Path(render({"X": a}, self.tmp / "f.html")).read_text(encoding="utf-8")
        self.assertIn("Fundamentals", html)
        self.assertIn("X &lt;Ltd&gt;", html)
        self.assertIn("Shareholding", html)
        a["fund"] = "no company figures found"
        self.assertIn("no company figures found", Path(render({"X": a}, self.tmp / "g.html")).read_text(encoding="utf-8"))

    def test_tech_summary(self):
        t = analyze(frame(np.linspace(10, 30, 260)))["tech"]
        self.assertEqual(t["ma_tally"]["reading"], "Strongly bullish")  # steady rise: price above every average
        self.assertEqual(len(t["ma"]), 12)
        self.assertEqual(next(o for o in t["osc"] if o["name"] == "RSI(14)")["signal"], "Overbought")
        p = t["pivots"]
        self.assertTrue(p["S3"] < p["S2"] < p["S1"] < p["Pivot"] < p["R1"] < p["R2"] < p["R3"])
        short = analyze(frame(np.linspace(30, 10, 80)))["tech"]  # too short for MA100/200: n/a, not counted
        self.assertEqual([m["signal"] for m in short["ma"] if m["name"] == "MA200"], ["n/a", "n/a"])
        self.assertEqual(short["ma_tally"]["reading"], "Strongly bearish")
        osc = lambda t, n: next(o for o in t["osc"] if o["name"] == n)["signal"]
        self.assertEqual(osc(tech_summary(frame(np.linspace(10, 12, 20))), "MACD(12,26)"), "n/a")  # too short
        stuck = frame(np.full(60, 10.0))
        stuck["high"] = stuck["low"] = stuck["close"]
        self.assertEqual(osc(tech_summary(stuck), "RSI(14)"), "n/a")  # floor-price freeze is not "Overbought"
        html = Path(render({"X": analyze(frame(np.linspace(10, 30, 260)))}, self.tmp / "t.html")).read_text(encoding="utf-8")
        self.assertIn("Technical summary", html)
        self.assertIn("not a forecast", html)




DECL = {"type": "Dividend", "summary": "Dividend Declaration",
        "body": "The Board of Directors has recommended 22.50% Cash Dividend for the year ended June 30, 2026. "
                "Date of AGM: 12.12.2026. Record Date: 17.11.2026. The Company has also reported EPS of Tk. 5.08."}


class WatchExtras(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_upcoming_dividend_formats(self):
        d = upcoming_dividend([DECL], pd.Timestamp("2026-11-04"))
        self.assertEqual((d["record"], d["pct"], d["tk"]), (pd.Timestamp("2026-11-17"), 22.5, 2.25))
        words = dict(DECL, body="recommended 1% Cash Dividend ... Record Date: 18th November 2026. EPS")
        self.assertEqual(upcoming_dividend([words], pd.Timestamp("2026-11-04"))["record"], pd.Timestamp("2026-11-18"))
        self.assertIsNone(upcoming_dividend([DECL], pd.Timestamp("2026-11-20")))  # record date already passed
        stock = dict(DECL, body="recommended 35% Stock Dividend. Record Date: 15.01.2026.")
        self.assertIsNone(upcoming_dividend([stock], pd.Timestamp("2026-01-01")))

    def test_dividend_lowers_only_horizons_that_pass_it(self):
        a = {"date": "2026-11-04", "close": 56.25,
             "forecast": {5: {"low": 50.0, "mid": 55.0, "high": 60.0}, 20: {"low": 45.0, "mid": 55.0, "high": 65.0}}}
        adjust_for_dividend(a, [DECL])  # 17 Nov is 8 Sun-Thu days after 4 Nov: past the 5-session horizon
        self.assertEqual(a["dividend"]["horizons"], [20])
        self.assertEqual(a["forecast"][5]["mid"], 55.0)
        self.assertAlmostEqual(a["forecast"][20]["mid"], 55.0 * (1 - 2.25 / 56.25))

    def test_log_and_score(self):
        idx = pd.bdate_range("2026-01-01", periods=30)
        close = pd.Series(np.full(30, 100.0), idx)
        close.iloc[10 + 5] = 120.0  # 5 sessions after the second forecast date: above its range
        res = lambda day: {"X": {"date": f"{day:%Y-%m-%d}", "close": 100.0,
                                 "forecast": {5: {"low": 90.0, "mid": 100.0, "high": 110.0}}}}
        path = self.tmp / "log.csv"
        log_forecasts(res(idx[0]), path)
        log_forecasts(res(idx[0]), path)  # same day twice: kept once
        log = log_forecasts(res(idx[10]), path)
        self.assertEqual(len(log), 2)
        log_forecasts({"X": dict(res(idx[28])["X"])}, path)  # not due yet
        sc = score_forecasts(pd.read_csv(path, dtype={"made_on": str}), {"X": close})
        self.assertEqual(sc["X"][5], {"checked": 2, "inside": 1, "below": 0, "above": 1})

    def test_data_warnings(self):
        thin = frame(np.linspace(5, 9, 80))  # 80 sessions, Tk 5-9 x 1,000 shares a day, under Tk 10
        w = data_warnings(thin)
        self.assertEqual(len(w), 3)
        self.assertIn("only 80 sessions", w[0])
        liquid = frame(np.linspace(100, 120, 260)).assign(volume=1e6)  # ~Tk 11 crore a day
        self.assertEqual(data_warnings(liquid), [])
        a = analyze(thin)
        a["score"], a["score_src"] = {5: {"checked": 0}}, "one-off"
        html = Path(render({"X": a}, self.tmp / "w.html")).read_text(encoding="utf-8")
        self.assertIn("Less tested here", html)
        self.assertIn("one_off_forecast_log.csv", html)

    def test_rates_line(self):
        p = self.tmp / "r.csv"
        pd.DataFrame({"month": [f"2026-{m:02d}" for m in range(1, 8)], "bond_yield": [9, 9, 9, 9, 9, 9, 10.0],
                      "deposit_rate": [8.0] * 7}).to_csv(p, index=False)
        rs = rates_status(p)
        self.assertEqual((rs["bond_yield"]["change"], rs["deposit_rate"]["change"]), (1.0, 0.0))
        df = frame(np.linspace(10, 30, 80))
        html = Path(render({"X": analyze(df)}, self.tmp / "w.html", rates=rs)).read_text(encoding="utf-8")
        self.assertIn("Rates have been rising", html)
        self.assertIn("WEAK", html)


if __name__ == "__main__":
    unittest.main()
