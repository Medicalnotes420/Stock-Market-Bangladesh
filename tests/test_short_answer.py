import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("short_answer", Path(__file__).resolve().parents[1] / "scripts" / "short_answer.py")
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

FULL = {
    "bar_date": "2026-11-09", "close": 55.8, "median_turnover_60d_mn": 0.3, "tested_shares_min_turnover_mn": 20,
    "dividend_ahead": {"tk_per_share": 2.25, "record_date": "2026-11-17", "sessions_away": 6, "range_lowered_pct": 4.0},
    "latest_quarter": {"fiscal_quarter": "Q1 (Jul-Sep 2026)", "eps": 0.34},
    "trend": "down", "rsi": 43.2, "moves_pct": {"1d": -0.7, "5d": -1.1, "20d": -3.5, "60d": -15.8},
    "support_20d": 52.0, "resistance_20d": 60.0,
    "ranges_80pct": {"5_sessions": {"low": 52.29, "mid": 54.96, "high": 58.93},
                     "20_sessions": {"low": 46.18, "mid": 51.18, "high": 63.86}},
    "alerts_fired": [], "rule_flags": [{"flag": "#21 Aroon Up below 90: x", "verdict": "no reliable forecast power"}],
    "track_record": {}, "eps": 5.08, "eps_period": "FY2026", "nav": 65.73, "nav_period": "FY2026", "pe": 10.98, "pb": 0.849,
}


class ShortAnswerTest(unittest.TestCase):
    def test_status_is_short_and_has_the_numbers(self):
        out = sa.lines("CROWNCEMNT", FULL)
        self.assertLessEqual(len(out), 9)
        text = "\n".join(out)
        for want in ("Tk 55.8 on 2026-11-09", "trend down", "5 sessions Tk 52.29-58.93", "20 sessions Tk 46.18-63.86",
                     "lowered 4%", "no scored track record", "Latest results: Q1 (Jul-Sep 2026) EPS Tk 0.34"):
            self.assertIn(want, text)

    def test_stock_adds_fundamentals_with_their_years(self):
        out = sa.lines("CROWNCEMNT", FULL, stock=True)
        self.assertLessEqual(len(out), 12)
        self.assertIn("EPS Tk 5.08, FY2026; NAV Tk 65.73, FY2026", "\n".join(out))
        self.assertIn("ROE 7.7%", "\n".join(out))

    def test_file_without_price_fields_says_so(self):
        s = {"bar_date": "2026-11-08", "close": 56.2}
        text = "\n".join(sa.lines("X", s))
        self.assertIn("not in this file yet", text)


if __name__ == "__main__":
    unittest.main()
