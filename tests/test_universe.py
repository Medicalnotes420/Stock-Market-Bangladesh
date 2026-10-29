import unittest

import numpy as np
import pandas as pd

from dse_quant.limits import lock_flags
from dse_quant.universe import UniverseRules, eligible
from tests.helpers import bars

RULES = UniverseRules(min_median_value=1e6, lookback=20, min_trade_frac=0.9, min_history=30,
                      min_price=10.0, no_lower_lock_days=3)


def market(n=60):
    good = bars("GOOD", [20.0 + 0.01 * i for i in range(n)], volume=100_000)       # value 2e6
    thin = bars("THIN", [20.0] * n, volume=1_000)                                   # value 2e4
    cheap = bars("CHEAP", [5.0] * n, volume=1_000_000)
    young = bars("YOUNG", [20.0] * 10, start=good.date.iloc[n - 10], volume=100_000)
    gappy = bars("GAPPY", [20.0] * n, volume=100_000).iloc[::2]                     # trades half the days
    bond = bars("SOMEBOND", [100.0] * n, volume=100_000)
    return lock_flags(pd.concat([good, thin, cheap, young, gappy, bond], ignore_index=True))


TYPES = {"GOOD": "Equity", "THIN": "Equity", "CHEAP": "Equity", "YOUNG": "Equity",
         "GAPPY": "Equity", "SOMEBOND": "Bond"}


class Filters(unittest.TestCase):
    def test_only_good_survives(self):
        df = market()
        self.assertEqual(eligible(df, df.date.max(), TYPES, RULES), ["GOOD"])

    def test_recent_lower_lock_excluded(self):
        df = market()
        last = df.date.max()
        df.loc[(df.ticker == "GOOD") & (df.date == last), "close"] = 18.0   # -10% lock
        df = lock_flags(df)
        self.assertEqual(eligible(df, last, TYPES, RULES), [])

    def test_must_trade_on_asof(self):
        df = market()
        last = df.date.max()
        df = df[~((df.ticker == "GOOD") & (df.date == last))]
        self.assertEqual(eligible(df, last, TYPES, RULES), [])


class NoLookAhead(unittest.TestCase):
    def test_future_rows_do_not_change_result(self):
        df = market(80)
        asof = df.date.sort_values().unique()[59]
        past = eligible(df[df.date <= asof], asof, TYPES, RULES)
        rng = np.random.default_rng(0)
        future = df.date > asof
        scrambled = df.copy()
        scrambled.loc[future, ["close", "volume", "value"]] = rng.uniform(0, 1e9, (future.sum(), 3))
        self.assertEqual(eligible(df, asof, TYPES, RULES), past)
        self.assertEqual(eligible(scrambled, asof, TYPES, RULES), past)


if __name__ == "__main__":
    unittest.main()
