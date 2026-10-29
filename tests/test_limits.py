import unittest

import pandas as pd

from dse_quant.limits import limit_pct, lock_flags
from tests.helpers import bars


class Tiers(unittest.TestCase):
    def test_boundaries(self):
        cases = {50: .10, 200: .10, 200.1: .0875, 500: .0875, 500.1: .075, 1000: .075,
                 1000.1: .0625, 2000: .0625, 2000.1: .05, 5000: .05, 5000.1: .0375}
        got = limit_pct(pd.Series(list(cases)))
        self.assertEqual(got.round(4).tolist(), list(cases.values()))

    def test_nan_prev_close(self):
        self.assertTrue(limit_pct(pd.Series([float("nan")])).isna().all())


class Locks(unittest.TestCase):
    def test_lower_lock_detected(self):
        df = lock_flags(bars("X", [100.0, 90.0, 90.0]))
        self.assertEqual(df.lower_lock.tolist(), [False, True, False])

    def test_near_but_not_at_limit(self):
        df = lock_flags(bars("X", [100.0, 90.5]))
        self.assertFalse(df.lower_lock.iloc[1])

    def test_upper_lock(self):
        df = lock_flags(bars("X", [100.0, 110.0]))
        self.assertTrue(df.upper_lock.iloc[1])

    def test_uses_tier_of_prev_close(self):
        # prev 1000 -> 7.5% -> lower limit 925
        df = lock_flags(bars("X", [1000.0, 925.0]))
        self.assertTrue(df.lower_lock.iloc[1])

    def test_per_ticker(self):
        df = lock_flags(pd.concat([bars("A", [100.0]), bars("B", [90.0])]))
        self.assertFalse(df.lower_lock.any())


if __name__ == "__main__":
    unittest.main()
