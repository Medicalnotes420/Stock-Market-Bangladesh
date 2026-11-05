import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from dse_quant.watch import SKEW_SHIFT, analyze, forecast, load_csv, parse_news, render


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


if __name__ == "__main__":
    unittest.main()
