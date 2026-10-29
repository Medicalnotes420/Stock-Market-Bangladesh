import unittest
from datetime import date

from dse_quant.risk import (
    LIMITS, Order, Portfolio, RiskGate, check_order, exit_list, size_position,
)


def pf(**kw):
    base = dict(equity=1_000_000.0, peak_equity=1_000_000.0, day_start_equity=1_000_000.0,
                positions={}, prices={}, sectors={})
    base.update(kw)
    return Portfolio(**base)


class LimitsAreFrozen(unittest.TestCase):
    def test_cannot_mutate(self):
        with self.assertRaises(Exception):
            LIMITS.max_position_pct = 1.0


class OrderChecks(unittest.TestCase):
    def test_negative_qty_rejected(self):
        with self.assertRaises(ValueError):
            Order("GP", -10, 100.0, "BUY")

    def test_bad_side_rejected(self):
        with self.assertRaises(ValueError):
            Order("GP", 10, 100.0, "SHORT")

    def test_sell_more_than_held_is_clipped(self):
        p = pf(positions={"GP": 50}, prices={"GP": 100.0})
        qty, why = check_order(Order("GP", 80, 100.0, "SELL"), p, adtv20=1e9, sector="Telecom")
        self.assertEqual(qty, 50)
        self.assertIn("long_only", why)

    def test_sell_with_no_holding_is_zero(self):
        qty, _ = check_order(Order("GP", 10, 100.0, "SELL"), pf(), adtv20=1e9, sector="Telecom")
        self.assertEqual(qty, 0)

    def test_portfolio_pct_cap(self):
        # 10% of 1,000,000 = 100,000 -> 1,000 shares at 100
        qty, why = check_order(Order("GP", 5_000, 100.0, "BUY"), pf(), adtv20=1e12, sector="Telecom")
        self.assertEqual(qty, 1_000)
        self.assertIn("max_position_pct", why)

    def test_cap_counts_existing_holding(self):
        p = pf(positions={"GP": 600}, prices={"GP": 100.0})
        qty, _ = check_order(Order("GP", 5_000, 100.0, "BUY"), p, adtv20=1e12, sector="Telecom")
        self.assertEqual(qty, 400)

    def test_adtv_cap(self):
        # 5% of ADTV 1,000,000 = 50,000 -> 500 shares
        qty, why = check_order(Order("GP", 5_000, 100.0, "BUY"), pf(), adtv20=1_000_000, sector="Telecom")
        self.assertEqual(qty, 500)
        self.assertIn("max_adtv_pct", why)

    def test_missing_adtv_blocks_buy(self):
        qty, why = check_order(Order("GP", 10, 100.0, "BUY"), pf(), adtv20=None, sector="Telecom")
        self.assertEqual(qty, 0)
        self.assertIn("no_adtv", why)

    def test_sector_cap(self):
        p = pf(positions={"A": 1300, "B": 1300}, prices={"A": 100.0, "B": 100.0},
               sectors={"A": "Bank", "B": "Bank"})
        # bank exposure 260,000; cap 300,000 -> room 40,000 -> 400 shares (below the 1,000 position cap)
        qty, why = check_order(Order("C", 5_000, 100.0, "BUY"), p, adtv20=1e12, sector="Bank")
        self.assertEqual(qty, 400)
        self.assertIn("max_sector_pct", why)

    def test_max_names(self):
        held = {f"T{i}": 1 for i in range(LIMITS.max_names)}
        p = pf(positions=held, prices={k: 1.0 for k in held})
        qty, why = check_order(Order("NEW", 10, 100.0, "BUY"), p, adtv20=1e12, sector="X")
        self.assertEqual(qty, 0)
        self.assertIn("max_names", why)


class Gate(unittest.TestCase):
    def setUp(self):
        self.ok_data = dict(latest_bar=date(2026, 10, 29), expected=date(2026, 10, 29),
                            missing_frac=0.0, has_index=True)

    def test_open_when_healthy(self):
        g = RiskGate(pf(), **self.ok_data)
        self.assertTrue(g.allow_new_entries)
        self.assertFalse(g.kill)

    def test_daily_loss_blocks_entries(self):
        g = RiskGate(pf(equity=979_000.0), **self.ok_data)
        self.assertFalse(g.allow_new_entries)
        self.assertIn("max_daily_loss", g.reasons)
        self.assertFalse(g.kill)

    def test_drawdown_triggers_kill(self):
        g = RiskGate(pf(equity=850_000.0, day_start_equity=850_000.0), **self.ok_data)
        self.assertTrue(g.kill)
        self.assertFalse(g.allow_new_entries)

    def test_stale_bar_blocks(self):
        d = dict(self.ok_data, latest_bar=date(2026, 10, 28))
        g = RiskGate(pf(), **d)
        self.assertFalse(g.allow_new_entries)
        self.assertIn("stale_data", g.reasons)

    def test_missing_universe_blocks(self):
        g = RiskGate(pf(), **dict(self.ok_data, missing_frac=0.06))
        self.assertFalse(g.allow_new_entries)

    def test_missing_index_blocks(self):
        g = RiskGate(pf(), **dict(self.ok_data, has_index=False))
        self.assertFalse(g.allow_new_entries)

    def test_buy_through_closed_gate_is_zero(self):
        g = RiskGate(pf(equity=979_000.0), **self.ok_data)
        qty, why = g.check(Order("GP", 10, 100.0, "BUY"), adtv20=1e12, sector="X")
        self.assertEqual(qty, 0)
        self.assertIn("gate_closed", why)

    def test_sell_through_closed_gate_allowed(self):
        p = pf(equity=850_000.0, day_start_equity=850_000.0, positions={"GP": 10}, prices={"GP": 100.0})
        g = RiskGate(p, **self.ok_data)
        qty, _ = g.check(Order("GP", 10, 100.0, "SELL"), adtv20=1e12, sector="X")
        self.assertEqual(qty, 10)


class DailyLoss(unittest.TestCase):
    def test_threshold(self):
        from dse_quant.risk import daily_loss_breached
        self.assertTrue(daily_loss_breached(98.0, 100.0))
        self.assertFalse(daily_loss_breached(98.1, 100.0))


class Sizing(unittest.TestCase):
    def test_vol_target(self):
        # 0.5% of 1,000,000 = 5,000 risk; ATR 2.5 -> 2,000 shares
        self.assertEqual(size_position(1_000_000, atr=2.5), 2_000)

    def test_bad_atr_is_zero(self):
        self.assertEqual(size_position(1_000_000, atr=0), 0)
        self.assertEqual(size_position(1_000_000, atr=float("nan")), 0)


class ExitList(unittest.TestCase):
    def test_orders_slowest_exit_first(self):
        p = pf(positions={"LIQ": 100, "ILLIQ": 100}, prices={"LIQ": 100.0, "ILLIQ": 100.0})
        rows = exit_list(p, adtv20={"LIQ": 1e9, "ILLIQ": 100_000})
        self.assertEqual(rows[0]["ticker"], "ILLIQ")
        self.assertEqual(rows[0]["days_to_exit"], 2)  # 10,000 / (5% of 100,000)
        self.assertEqual(rows[1]["days_to_exit"], 1)

    def test_unknown_adtv_flagged(self):
        p = pf(positions={"X": 10}, prices={"X": 10.0})
        rows = exit_list(p, adtv20={})
        self.assertIsNone(rows[0]["days_to_exit"])


if __name__ == "__main__":
    unittest.main()
