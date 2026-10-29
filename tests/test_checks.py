import unittest

import pandas as pd

from dse_quant.data.checks import data_status, ohlc_bad, unexplained_gaps
from tests.helpers import bars


class Ohlc(unittest.TestCase):
    def test_flags_bad_rows(self):
        df = bars("X", [10.0, 10.0, 10.0, 10.0])
        df.loc[1, "high"] = 9.0        # high < close
        df.loc[2, "close"] = 0.0
        df.loc[3, "open"] = 11.0       # open > high
        self.assertEqual(ohlc_bad(df).tolist(), [False, True, True, True])


class Gaps(unittest.TestCase):
    def test_gap_beyond_limit_without_action_flagged(self):
        df = bars("X", [100.0, 50.0, 51.0])
        empty = pd.DataFrame(columns=["ticker", "date", "ratio"])
        g = unexplained_gaps(df, empty)
        self.assertEqual(g.date.tolist(), [df.date.iloc[1]])

    def test_gap_explained_by_action_not_flagged(self):
        df = bars("X", [100.0, 50.0, 51.0])
        acts = pd.DataFrame({"ticker": ["X"], "date": [df.date.iloc[1]], "ratio": [2.0]})
        self.assertEqual(len(unexplained_gaps(df, acts)), 0)

    def test_tick_rounding_on_cheap_stock_ok(self):
        # prev 4.5: +10% limit = 4.95, rounds to the next tick 5.0 = +11.1%
        df = bars("X", [4.5, 5.0])
        self.assertEqual(len(unexplained_gaps(df, pd.DataFrame(columns=["ticker", "date", "ratio"]))), 0)

    def test_move_within_limit_ok(self):
        df = bars("X", [100.0, 91.0])
        self.assertEqual(len(unexplained_gaps(df, pd.DataFrame(columns=["ticker", "date", "ratio"]))), 0)


class Status(unittest.TestCase):
    def setUp(self):
        self.df = pd.concat([bars("00DSEX", [5000.0] * 3), bars("A", [10.0] * 3), bars("B", [10.0] * 2)])
        self.last = self.df.date.max()

    def test_feeds_risk_gate(self):
        s = data_status(self.df, expected=self.last, universe=["A", "B"])
        self.assertEqual(s["latest_bar"], self.last.date())
        self.assertEqual(s["expected"], self.last.date())
        self.assertAlmostEqual(s["missing_frac"], 0.5)
        self.assertTrue(s["has_index"])

    def test_index_missing(self):
        s = data_status(self.df[self.df.ticker != "00DSEX"], expected=self.last, universe=["A"])
        self.assertFalse(s["has_index"])


if __name__ == "__main__":
    unittest.main()
