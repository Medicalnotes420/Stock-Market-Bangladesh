import unittest
from decimal import Decimal

import pandas as pd

from dse_quant.backtest.costs import cost_rate
from dse_quant.limits import lock_flags
from dse_quant.panels import build_panels
from dse_quant.paper.book import decide, fill_pending, new_book, stop_checks
from tests.helpers import bars


class Stub:
    """Wants ticker 0 on chosen sessions, exits on chosen sessions."""

    def __init__(self, buy=(), sell=()):
        self.buy, self.sell = set(buy), set(sell)

    def entries(self, t):
        return [0] if t in self.buy else []

    def exit(self, t, j, pos):
        return t in self.sell


def panel(closes):
    b = bars("S", closes, volume=1e9)
    p = build_panels(lock_flags(b.assign(close_raw=b.close, gap_flag=False)))
    p.atr.iloc[:, :], p.adtv.iloc[:, :], p.vol.iloc[:, :] = 1.0, 1e10, 0.0
    return p


A = {"S": "A"}  # T+2; without a category the book assumes Z (T+3)


def run_days(p, strat, days, book=None, regime="RISK_ON", categories=A):
    book = book or new_book(1e6)
    for t in range(days):
        fill_pending(book, p, t, categories=categories)
        decide(book, strat, p, t, regime=regime, gate_open=True)
    return book


class Book(unittest.TestCase):
    def test_buy_fills_next_day_at_typical_price_with_costs(self):
        p = panel([10.0] * 5)
        book = run_days(p, Stub(buy={0}), 2)
        self.assertEqual(book["positions"]["S"], 5000)          # 0.5% of 1e6 / ATR 1
        rate = float(cost_rate(50_000, 1e10, 0.0))
        self.assertAlmostEqual(book["cash"], 1e6 - 5000 * 10 * (1 + rate))

    def test_exit_waits_for_t_plus_2(self):
        p = panel([10.0] * 8)
        book = run_days(p, Stub(buy={0}, sell={1}), 3)          # buy fills t1; sell wanted t1 -> earliest fill t3
        self.assertIn("S", book["positions"])
        book = run_days(p, Stub(buy={0}, sell={1}), 4)
        self.assertNotIn("S", book["positions"])

    def test_cat_z_and_unknown_category_wait_for_t_plus_3(self):
        p = panel([10.0] * 8)
        for cats in ({"S": "Z"}, {}, {"S": "Q"}):
            book = run_days(p, Stub(buy={0}, sell={1}), 4, categories=cats)       # t3 would fill under T+2
            self.assertIn("S", book["positions"])
            book = run_days(p, Stub(buy={0}, sell={1}), 5, categories=cats)
            self.assertNotIn("S", book["positions"])

    def test_sale_proceeds_clear_after_the_lag(self):
        p = panel([10.0] * 10)
        book = run_days(p, Stub(buy={0}, sell={1}), 4)                           # sold at t3
        self.assertEqual(len(book["unsettled_cash"]), 1)
        self.assertLess(book["cash"], Decimal(960_000))                          # proceeds not spendable yet
        book = run_days(p, Stub(buy={0}, sell={1}), 6, categories=A)             # t5: proceeds cleared
        self.assertEqual(book["unsettled_cash"], [])
        self.assertGreater(book["cash"], Decimal(999_000))

    def test_no_sell_on_lower_lock_and_it_is_counted(self):
        p = panel([10.0, 10.0, 10.0, 10.0, 9.0, 9.0])           # t4 locked down
        book = run_days(p, Stub(buy={0}, sell={3}), 5)
        self.assertIn("S", book["positions"])
        self.assertEqual(book["exit_attempts"][-1], 1)

    def test_no_entries_in_risk_off(self):
        p = panel([10.0] * 4)
        book = run_days(p, Stub(buy={0, 1, 2}), 4, regime="RISK_OFF")
        self.assertEqual(book["positions"], {})


class Stops(unittest.TestCase):
    def test_stale_data_while_holding_stops(self):
        b = new_book(1e6)
        b["positions"] = {"S": 10}
        for _ in range(3):
            stop_checks(b, stale=True, kill=False)
        self.assertIn("stale", b["stopped"])

    def test_poor_live_results_after_60_sessions_stop(self):
        b = new_book(1e6)
        b["returns"] = [-0.001, 0.0005] * 30
        stop_checks(b, stale=False, kill=False)
        self.assertIn("live Sharpe", b["stopped"])

    def test_good_live_results_do_not_stop(self):
        b = new_book(1e6)
        b["returns"] = [0.002, -0.0005] * 30
        stop_checks(b, stale=False, kill=False)
        self.assertIsNone(b["stopped"])

    def test_blocked_exits_stop(self):
        b = new_book(1e6)
        b["exit_attempts"] = [1, 1, 0, 0, 0]
        stop_checks(b, stale=False, kill=False)
        self.assertIn("lower-limit", b["stopped"])

    def test_stopped_book_takes_no_entries_and_sells_all(self):
        p = panel([10.0] * 6)
        book = run_days(p, Stub(buy={0}), 4)
        book["stopped"] = "test"
        decide(book, Stub(buy={4}), p, 4, regime="RISK_ON", gate_open=True)
        self.assertEqual(book["pending_buys"], {})
        self.assertEqual(book["pending_sells"], ["S"])


if __name__ == "__main__":
    unittest.main()
