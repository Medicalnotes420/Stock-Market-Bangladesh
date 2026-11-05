import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rates_signal import by_start, fresh_check, samples, verdict  # noqa: E402


class TestRatesSignal(unittest.TestCase):
    def test_samples_align_past_change_with_future_return(self):
        idx = pd.period_range("2013-01", periods=8, freq="M")
        m = pd.DataFrame({"bond_yield": [5, 5, 6, 6, 6, 6, 6, 6.0], "dsex": [100, 100, 100, 90, 90, 90, 90, 90.0]}, idx)
        d = samples(m, 2)
        self.assertAlmostEqual(d.loc[pd.Period("2013-03", "M"), "signal"], 1.0)  # 6 - 5 over 2 months
        self.assertAlmostEqual(d.loc[pd.Period("2013-03", "M"), "outcome"], -0.1)  # 100 -> 90 two months on

    def test_non_overlapping_starts(self):
        d = pd.DataFrame({"signal": np.arange(12.0), "outcome": -np.arange(12.0)})
        r = by_start(d, 3)
        self.assertEqual(list(r.n), [4, 4, 4])
        self.assertTrue((r.rho < -0.99).all())

    def test_fresh_check_uses_only_new_months(self):
        idx = pd.period_range("2026-05", periods=4, freq="M")  # May, Jun (in-sample), Jul, Aug (fresh)
        d = pd.DataFrame({"signal": [1.0, 1.0, 0.5, -0.5], "outcome": [0.5, 0.5, -0.02, 0.03]}, idx)
        f = fresh_check(d)
        self.assertEqual((f["months"], f["rising"], f["not_rising"]), (2, 1, 1))
        self.assertTrue(f["agrees"])

    def test_verdict_rules(self):
        neg = pd.DataFrame({"rho": [-0.5, -0.4], "p": [0.01, 0.02]})
        self.assertEqual(verdict(neg, neg, [-0.3, -0.2]), "HOLDS IN-SAMPLE")
        self.assertEqual(verdict(neg.assign(p=0.2), neg, [-0.3, -0.2]), "WEAK")
        self.assertEqual(verdict(neg.assign(rho=[-0.5, 0.1]), neg, [-0.3, -0.2]), "NO")


if __name__ == "__main__":
    unittest.main()
