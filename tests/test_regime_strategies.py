import unittest

import numpy as np
import pandas as pd

from dse_quant.limits import lock_flags
from dse_quant.panels import build_panels
from dse_quant.regime import classify, fill_index, proxy_returns
from dse_quant.strategies import GRIDS, make
from tests.helpers import bars


def mkt(n, drift, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    noise = np.full(n, 0.004)
    noise[-30:] = 0.001  # calm finish so the volatility percentile is low at the last bar
    dsex = 5000 * np.cumprod(1 + drift + rng.normal(0, 1, n) * noise)
    return pd.DataFrame({"dsex": dsex, "turnover": 1e10, "adv": 200 if drift > 0 else 100,
                         "dec": 100 if drift > 0 else 200, "n": 300}, index=idx)


class Regime(unittest.TestCase):
    def test_rising_is_risk_on(self):
        m = mkt(400, 0.002)
        r = classify(m, pct_above_50=pd.Series(0.7, m.index), lock_frac=pd.Series(0.0, m.index))
        self.assertEqual(r.iloc[-1], "RISK_ON")

    def test_falling_is_risk_off(self):
        m = mkt(400, -0.002)
        r = classify(m, pct_above_50=pd.Series(0.2, m.index), lock_frac=pd.Series(0.0, m.index))
        self.assertEqual(r.iloc[-1], "RISK_OFF")

    def test_lock_stress(self):
        m = mkt(400, 0.002)
        lf = pd.Series(0.0, m.index)
        lf.iloc[-1] = 0.2
        r = classify(m, pct_above_50=pd.Series(0.7, m.index), lock_frac=lf)
        self.assertEqual(r.iloc[-1], "STRESS")

    def test_regime_at_t_ignores_future(self):
        m = mkt(400, 0.001, seed=3)
        a = pd.Series(0.5, m.index)
        z = pd.Series(0.0, m.index)
        full = classify(m, a, z)
        cut = classify(m.iloc[:300], a.iloc[:300], z.iloc[:300])
        pd.testing.assert_series_equal(full.iloc[:300], cut)

    def test_fill_index_chains_proxy_only_on_missing_days(self):
        nan = float("nan")
        out = fill_index(pd.Series([100.0, nan, nan, 110.0]), pd.Series([nan, 0.01, -0.02, 0.5]))
        self.assertEqual(out.round(4).tolist(), [100.0, 101.0, 98.98, 110.0])

    def test_proxy_is_median_return(self):
        df = pd.concat([bars("A", [10, 11]), bars("B", [10, 10]), bars("C", [10, 9])])
        df = df.assign(close_raw=df.close, gap_flag=False)
        r = proxy_returns(build_panels(lock_flags(df)), {"A": "Equity", "B": "Equity", "C": "Equity"})
        self.assertAlmostEqual(r.iloc[1], 0.0)


class StrategiesNoLookAhead(unittest.TestCase):
    def test_entries_at_t_unchanged_by_future(self):
        rng = np.random.default_rng(7)
        frames = []
        for k in range(15):
            closes = 20 * np.cumprod(1 + rng.normal(0.0005 * (k - 7), 0.02, 400))
            b = bars(f"T{k}", closes.round(1), volume=float(rng.integers(5e5, 5e6)))
            b["high"], b["low"] = b.close * 1.01, b.close * 0.99
            frames.append(b)
        df = lock_flags(pd.concat(frames).assign(close_raw=lambda d: d.close, gap_flag=False))
        full = build_panels(df)
        t = 330
        cut = build_panels(df[df.date <= full.dates[t]])
        for name, grid in GRIDS.items():
            for params in grid:
                a, b = make(name, params), make(name, params)
                a.prepare(full)
                b.prepare(cut)
                for tt in range(300, t + 1):
                    self.assertEqual(a.entries(tt), b.entries(tt), (name, params, tt))


if __name__ == "__main__":
    unittest.main()
