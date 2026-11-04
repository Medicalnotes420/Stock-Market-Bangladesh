import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from dse_quant.watch import analyze, load_csv, render


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

    def test_render_escapes_and_has_disclaimer(self):
        out = render({"<script>x</script>": analyze(frame(np.linspace(10, 30, 80)))}, self.tmp / "w.html",
                     note="<b>n</b>", errors=["<img src=x>"])
        html = Path(out).read_text(encoding="utf-8")
        self.assertIn("<svg", html)
        self.assertIn("Not investment advice", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
