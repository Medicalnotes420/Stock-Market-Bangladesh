import unittest
from datetime import date

from dse_quant.sessions import closed_reason, expected_session

D = date.fromisoformat
# asof, why the DSE is closed that day (None = a session), the session a run "as of" that day should hold.
# Dates are real ones from data/clean/market.csv (see config/workflow.toml).
GOLDEN = [
    ("2026-10-27", None, "2026-10-27"),             # plain Tuesday
    ("2026-11-08", None, "2026-11-08"),             # Sunday is a trading day
    ("2026-10-30", "dse_weekend", "2026-10-29"),    # Friday
    ("2026-10-31", "dse_weekend", "2026-10-29"),    # Saturday
    ("2026-02-11", "market_closed", "2026-02-10"),  # two closed weekdays in a row
    ("2026-02-12", "market_closed", "2026-02-10"),
    ("2026-03-23", "market_closed", "2026-03-16"),  # last day of a closed week, across a weekend
    ("2026-05-23", None, "2026-05-23"),             # Saturday make-up session
    ("2026-05-31", "market_closed", "2026-05-24"),  # closed week that follows it
    ("2026-10-17", None, "2026-10-17"),             # Saturday make-up session
    ("2026-10-22", "market_closed", "2026-10-19"),
    ("2024-08-05", "market_closed", "2024-08-04"),  # single closed Monday
    ("2020-05-30", "dse_weekend", "2020-03-25"),    # end of the 67-day closure
    ("2020-05-31", None, "2020-05-31"),
]


class Sessions(unittest.TestCase):
    def test_golden_dates(self):
        for asof, reason, session in GOLDEN:
            with self.subTest(asof=asof):
                self.assertEqual(closed_reason(asof), reason)
                self.assertEqual(expected_session(asof), D(session))

    def test_unlisted_weekday_counts_as_a_session(self):  # fail-safe: an unknown holiday shows up as stale data
        self.assertIsNone(closed_reason("2031-01-01"))


if __name__ == "__main__":
    unittest.main()
