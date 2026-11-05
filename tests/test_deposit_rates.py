import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from deposit_rates import best_p, residual, together, verdicts  # noqa: E402


def row(rho, p, neg=None):
    return {"rho": rho, "p": p, "n": 20, "all_negative": neg}


BASE = {"P1": row(-0.5, 0.20), "P2": row(0.1, 0.6), "P3": row(-0.4, 0.30, True), "P4": row(-0.3, 0.40, True),
        "P1 1998-2011": row(-0.3, 0.3), "P1 2012-2025": row(-0.4, 0.2), "P4 no floor": row(-0.2, 0.5, True)}


class TestDepositRates(unittest.TestCase):
    def test_together_uses_the_same_window(self):
        idx = pd.period_range("2013-01", periods=4, freq="M")
        m = pd.DataFrame({"deposit": [6, 7, 7, 7.0], "dsex": [100, 90, 90, 90.0]}, idx)
        d = together(m, 1, "deposit")
        self.assertAlmostEqual(d.loc[pd.Period("2013-02", "M"), "signal"], 1.0)
        self.assertAlmostEqual(d.loc[pd.Period("2013-02", "M"), "outcome"], -0.1)

    def test_residual_removes_the_bond_part(self):
        idx = pd.period_range("2013-01", periods=30, freq="M")
        bond = np.linspace(5, 12, 30)
        m = pd.DataFrame({"deposit": 2 * bond + 1, "bond_yield": bond, "dsex": 100.0}, idx)
        self.assertLess(residual(m, 6).abs().max(), 1e-9)  # fully explained by bonds -> nothing left

    def test_verdicts(self):
        self.assertEqual(verdicts(BASE), ("NONE", "NONE"))
        strong = dict(BASE, P1=row(-0.6, 0.004))
        self.assertEqual(verdicts(strong)[0], "ASSOCIATION EXISTS")
        self.assertEqual(verdicts(dict(strong, **{"P1 1998-2011": row(0.1, 0.7)}))[0], "WEAK")  # a half disagrees
        self.assertEqual(verdicts(dict(BASE, P4=row(-0.5, 0.03, True)))[1], "WEAK")
        self.assertEqual(best_p(dict(BASE, P4=row(-0.5, 0.001, False)), ["P4"]), 1.0)  # not every start negative


if __name__ == "__main__":
    unittest.main()
