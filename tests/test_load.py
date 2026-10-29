import unittest

import pandas as pd

from dse_quant.data.load import repair_a1_dates
from tests.helpers import bars


def a1_from(ref, swap_dates=()):
    """Make an A1-style frame from ref, with given true dates written day/month swapped."""
    a1 = ref.copy()
    for d in map(pd.Timestamp, swap_dates):
        a1.loc[a1.date == d, "date"] = pd.Timestamp(year=d.year, month=d.day, day=d.month)
    return a1


class RepairA1(unittest.TestCase):
    def setUp(self):
        # trading every business day Jan-Jun 2020; prices distinct per day so votes are decisive
        n = 130
        self.ref = pd.concat([bars(t, [10 + i * 0.5 + k for i in range(n)]) for k, t in enumerate("ABC")])

    def test_swapped_block_is_restored(self):
        a1 = a1_from(self.ref, ["2020-03-05"])           # true 5 Mar written as 3 May
        out, rep = repair_a1_dates(a1, self.ref)
        m = out.merge(self.ref, on=["ticker", "date"], suffixes=("", "_r"))
        self.assertTrue((m.close == m.close_r).all())
        self.assertEqual(len(out), len(self.ref))
        self.assertGreaterEqual(rep["swapped_dates"], 1)

    def test_dead_ticker_follows_the_vote(self):
        dead = bars("DEAD", [5.0] * 130)
        a1 = pd.concat([a1_from(self.ref, ["2020-03-05"]), a1_from(dead, ["2020-03-05"])])
        out, _ = repair_a1_dates(a1, self.ref)
        self.assertIn(pd.Timestamp("2020-03-05"), set(out[out.ticker == "DEAD"].date))

    def test_rows_before_ref_start_dropped(self):
        early = bars("A", [1.0, 1.0], start="2019-06-03")
        out, rep = repair_a1_dates(pd.concat([early, self.ref]), self.ref)
        self.assertGreaterEqual(out.date.min(), self.ref.date.min())
        self.assertEqual(rep["dropped_pre_ref"], 2)

    def test_conflicting_duplicates_dropped(self):
        dup = self.ref.iloc[[0]].assign(close=999.0)
        out, rep = repair_a1_dates(pd.concat([self.ref, dup]), self.ref)
        self.assertEqual(rep["conflicting_dups"], 1)
        self.assertFalse(((out.ticker == "A") & (out.date == self.ref.date.iloc[0])).any())

    def test_ticker_whitespace_stripped(self):
        out, _ = repair_a1_dates(self.ref.assign(ticker=self.ref.ticker + " "), self.ref)
        self.assertEqual(set(out.ticker), {"A", "B", "C"})


if __name__ == "__main__":
    unittest.main()
