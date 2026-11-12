import importlib
import random
import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from chartapp import patterns, runner as R
from chartapp.bars import Bar, Row
from chartapp.patterns import Detection, Point, Segment

D0 = date(2026, 1, 1)


def make(n, gaps=(), seed=3):
    """n rows on consecutive days with a random walk close; rows at the `gaps` indices carry gap_flag."""
    rng, close, out = random.Random(seed), 100, []
    for i in range(n):
        close = max(5, close + rng.randint(-4, 4))
        c = Decimal(close)
        out.append(Row(D0 + timedelta(days=i), c, c + 1, c - 1, c, 1000, c * 1000, c, Decimal("1.0"),
                       i in gaps, False, False))
    return out


def plugin(detect, lookback=20, **defaults):
    return SimpleNamespace(NAME="fake", VERSION=1, LOOKBACK=lookback, DEFAULTS=defaults, detect=detect)


def always(bars, cfg):
    return Detection("neutral", points=(Point(bars[-1].date, bars[-1].close, "last"),))


def up_day(bars, cfg):
    if len(bars) >= 2 and bars[-1].close > bars[-2].close:
        return Detection("bullish", levels={"prev": bars[-2].close})


def days(signals):
    return [(s.signal_date - D0).days for s in signals]


class Slicing(unittest.TestCase):
    def test_plugin_gets_plain_bars_ending_at_the_signal_bar(self):
        seen = []
        rows = make(30)
        R.run(plugin(lambda bars, cfg: seen.append(bars), lookback=7), {}, "T", rows)
        self.assertEqual(len(seen), 30)
        for i, bars in enumerate(seen):
            self.assertEqual(len(bars), min(i + 1, 7))
            self.assertEqual(bars[-1].date, rows[i].date)
            self.assertEqual([b.date for b in bars], [r.date for r in rows[max(0, i - 6):i + 1]])
            self.assertTrue(all(type(b) is Bar for b in bars))  # not Row: no adj_factor, no flags

    def test_signal_fields(self):
        p = plugin(always, a=1)
        s = R.run(p, {"a": 1}, "TICK", make(3))[2]
        self.assertEqual((s.pattern, s.version, s.ticker, s.signal_date), ("fake", 1, "TICK", D0 + timedelta(days=2)))
        self.assertEqual(s.config_hash, R.config_hash({"a": 1}))
        self.assertEqual(s.detection.points[0].date, s.signal_date)

    def test_a_shorter_history_gives_the_same_signals(self):
        rows = make(200, gaps={60})
        ex = [D0 + timedelta(days=120)]
        for p in (plugin(up_day, lookback=15), plugin(always, lookback=5)):
            full = R.run(p, {}, "T", rows, ex)
            self.assertGreater(len(full), 20)
            for k in range(len(rows) + 1):
                want = [s for s in full if s.signal_date <= rows[k - 1].date] if k else []
                self.assertEqual(R.run(p, {}, "T", rows[:k], ex), want, k)

    def test_an_ex_date_still_in_the_future_changes_nothing(self):
        rows, p = make(200), plugin(always, lookback=15)
        for future in (100, 101, 110, 199, 400):  # day of the ex-date; the history ends at day 99
            self.assertEqual(R.run(p, {}, "T", rows[:100], [D0 + timedelta(days=future)]),
                             R.run(p, {}, "T", rows[:100], []), future)


class Blocked(unittest.TestCase):
    def test_gap_bar_blocks_every_window_that_holds_it(self):
        got = days(R.run(plugin(always, lookback=5), {}, "T", make(20, gaps={8})))
        self.assertEqual(got, [0, 1, 2, 3, 4, 5, 6, 7, 13, 14, 15, 16, 17, 18, 19])  # 8..12 hold bar 8

    def test_ten_bars_from_an_ex_date_are_blocked(self):
        ex = [D0 + timedelta(days=5)]
        got = days(R.run(plugin(always, lookback=30), {}, "T", make(20), ex))
        self.assertEqual(got, [0, 1, 2, 3, 4, 15, 16, 17, 18, 19])  # 5..14 blocked, the 10 sessions it takes

    def test_ex_date_with_no_bar_of_its_own_still_blocks(self):
        rows = [r for r in make(20) if (r.date - D0).days != 5]
        got = days(R.run(plugin(always, lookback=30), {}, "T", rows, [D0 + timedelta(days=5)]))
        self.assertEqual(got, [0, 1, 2, 3, 4, 15, 16, 17, 18, 19])  # blocked from the next bar, 6, to 14

    def test_window_entirely_after_the_ex_date_is_not_blocked(self):
        # adjustment only rescales bars before the ex-date, so a window that starts after it is unaffected
        ex = [D0 + timedelta(days=5)]
        got = days(R.run(plugin(always, lookback=3), {}, "T", make(20), ex))
        self.assertEqual(got, [0, 1, 2, 3, 4, *range(8, 20)])  # only 5, 6, 7 have bar 5 in their window

    def test_future_and_other_ex_dates_do_not_block(self):
        ex = [D0 - timedelta(days=30), D0 + timedelta(days=500)]
        self.assertEqual(days(R.run(plugin(always), {}, "T", make(12), ex)), list(range(12)))


class Contract(unittest.TestCase):
    def fails(self, detect):
        with self.assertRaises(R.PluginContractError):
            R.run(plugin(detect, lookback=3), {}, "T", make(10))

    def test_point_outside_the_window(self):
        self.fails(lambda bars, cfg: Detection("neutral", points=(Point(D0 + timedelta(days=99), Decimal(1), "x"),)))
        # bar 0 exists, but a 3-bar window ending at bar 9 was never given it
        self.fails(lambda bars, cfg: Detection("neutral", points=(Point(D0, Decimal(1), "x"),))
                   if len(bars) == 3 and bars[0].date > D0 else None)

    def test_segment_outside_the_window(self):
        far = Point(D0 + timedelta(days=99), Decimal(1), "end")
        self.fails(lambda bars, cfg: Detection("neutral", segments=(
            Segment(Point(bars[-1].date, Decimal(1), "start"), far, "support"),)))

    def test_floats_are_refused(self):
        self.fails(lambda bars, cfg: Detection("neutral", points=(Point(bars[-1].date, 1.5, "x"),)))
        self.fails(lambda bars, cfg: Detection("neutral", levels={"breakout": 1.5}))
        self.fails(lambda bars, cfg: Detection("neutral", score=0.5))

    def test_nan_infinity_and_out_of_range_are_refused(self):
        self.fails(lambda bars, cfg: Detection("neutral", points=(Point(bars[-1].date, Decimal("NaN"), "x"),)))
        self.fails(lambda bars, cfg: Detection("neutral", levels={"breakout": Decimal("Infinity")}))
        self.fails(lambda bars, cfg: Detection("neutral", score=Decimal("Infinity")))
        self.fails(lambda bars, cfg: Detection("neutral", score=Decimal(5)))
        self.fails(lambda bars, cfg: Detection("neutral", score=Decimal("-0.1")))

    def test_exponent_notation_is_refused(self):
        self.assertEqual(str(Decimal("0.0") * Decimal("0.000125")), "0E-7")  # how one arises
        self.fails(lambda bars, cfg: Detection("neutral", levels={"x": Decimal("0.0") * Decimal("0.000125")}))
        self.fails(lambda bars, cfg: Detection("neutral", points=(Point(bars[-1].date, Decimal("1E+2"), "x"),)))
        self.fails(lambda bars, cfg: Detection("neutral", score=Decimal("0E-7")))

    def test_text_fields_must_be_text(self):
        self.fails(lambda bars, cfg: Detection("neutral", note=1.5))
        self.fails(lambda bars, cfg: Detection("neutral", points=(Point(bars[-1].date, Decimal(1), 1.5),)))
        self.fails(lambda bars, cfg: Detection("neutral", levels={1.5: Decimal(1)}))
        here = lambda bars: Point(bars[-1].date, Decimal(1), "p")  # noqa: E731
        self.fails(lambda bars, cfg: Detection("neutral", segments=(Segment(here(bars), here(bars), 2.5),)))

    def test_containers_must_be_the_right_kind(self):
        self.fails(lambda bars, cfg: Detection("neutral", points=(p for p in ())))  # a generator
        self.fails(lambda bars, cfg: Detection("neutral", points=[Point(bars[-1].date, Decimal(1), "x")]))
        self.fails(lambda bars, cfg: Detection("neutral", levels=[1]))
        self.fails(lambda bars, cfg: Detection("neutral", points=("not a point",)))
        self.fails(lambda bars, cfg: Detection("neutral", segments=("not a segment",)))

    def test_a_full_valid_detection_passes(self):
        def detect(bars, cfg):
            a, b = Point(bars[0].date, bars[0].low, "from"), Point(bars[-1].date, bars[-1].high, "to")
            return Detection("bearish", (a, b), (Segment(a, b, "resistance"),), {"breakout": bars[-1].close},
                             Decimal("0.75"), "ok")
        self.assertEqual(len(R.run(plugin(detect, lookback=3), {}, "T", make(10))), 10)

    def test_wrong_return_and_direction(self):
        self.fails(lambda bars, cfg: True)
        self.fails(lambda bars, cfg: Detection("up"))

    def test_plugin_shape(self):
        ok = dict(NAME="p", VERSION=1, LOOKBACK=5, DEFAULTS={"n": 1}, detect=always)
        self.assertEqual(R._checked(SimpleNamespace(**ok)).NAME, "p")
        for change in ({"NAME": 1}, {"VERSION": True}, {"LOOKBACK": 0}, {"DEFAULTS": {"x": 0.5}},
                       {"DEFAULTS": {"x": Decimal("NaN")}},
                       {"DEFAULTS": {"enabled": True}}, {"detect": None}):
            with self.assertRaises(R.PluginContractError, msg=change):
                R._checked(SimpleNamespace(**{**ok, **change}))
        broken = SimpleNamespace(**ok)
        del broken.LOOKBACK
        with self.assertRaises(R.PluginContractError):
            R._checked(broken)


class Config(unittest.TestCase):
    PLUGINS = {"alpha": SimpleNamespace(NAME="alpha", DEFAULTS={"left": 5, "pct": Decimal("0.5"), "on": True,
                                                                "mode": "close"}),
               "beta": SimpleNamespace(NAME="beta", DEFAULTS={})}

    def conf(self, text):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "patterns.toml"
        p.write_text(text, encoding="utf-8")
        return R.configure(self.PLUGINS, p)

    def test_missing_file_means_defaults(self):
        got = R.configure(self.PLUGINS, Path(tempfile.gettempdir()) / "no-such-patterns.toml")
        self.assertEqual({k: dict(v) for k, v in got.items()},
                         {"alpha": self.PLUGINS["alpha"].DEFAULTS, "beta": {}})

    def test_overrides_stay_decimal(self):
        got = self.conf('[alpha]\nleft = 3\npct = 1.25\non = false\nmode = "high"\n')["alpha"]
        self.assertEqual(dict(got), {"left": 3, "pct": Decimal("1.25"), "on": False, "mode": "high"})
        self.assertIs(type(got["pct"]), Decimal)
        with self.assertRaises(TypeError):
            got["left"] = 9  # plugins cannot change their config

    def test_disabled_plugin_is_left_out(self):
        self.assertEqual(list(self.conf("[alpha]\nenabled = false\n")), ["beta"])

    def test_mistakes_are_errors(self):
        for text in ("[gamma]\n", "[alpha]\nrigth = 3\n", "[alpha]\nleft = true\n", "[alpha]\nleft = 3.0\n",
                     "[alpha]\npct = 1\n", '[alpha]\non = "yes"\n', "[alpha]\nmode = 3\n", "[alpha]\nenabled = 1\n",
                     "[alpha]\npct = nan\n", "[alpha]\npct = inf\n", "alpha = 3\n", 'alpha = "x"\n',
                     'alpha = [["pct", 1.0]]\n', "[alpha]\nleft = [1]\n", "[alpha.left]\nx = 1\n"):
            with self.assertRaises(ValueError, msg=text):
                self.conf(text)

    def test_plugins_own_check_runs_at_load(self):
        def check(cfg):
            if cfg["left"] > 9:
                raise ValueError("left too big")
        plugins = {"alpha": SimpleNamespace(NAME="alpha", DEFAULTS={"left": 5}, check=check)}
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "patterns.toml"
        p.write_text("[alpha]\nleft = 9\n", encoding="utf-8")
        self.assertEqual(dict(R.configure(plugins, p)["alpha"]), {"left": 9})
        for text in ("[alpha]\nleft = 10\n", "[alpha]\nenabled = false\nleft = 10\n"):  # checked even when off
            p.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"\[alpha\] left too big"):
                R.configure(plugins, p)

    def test_hash_follows_the_config(self):
        a, b = R.config_hash({"left": 5, "pct": Decimal("0.5")}), R.config_hash({"pct": Decimal("0.5"), "left": 5})
        self.assertEqual(a, b)
        self.assertRegex(a, r"^[0-9a-f]{8}$")
        self.assertNotEqual(a, R.config_hash({"left": 5, "pct": Decimal("0.6")}))


class Files(unittest.TestCase):
    def test_ex_dates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "actions.csv"
            p.write_text("ticker,date,ratio\nBBB,2016-11-21,1.02\nAAA,2017-10-03,1.01\nAAA,2015-03-03,2.0\n")
            self.assertEqual(R.ex_dates(p), {"BBB": [date(2016, 11, 21)],
                                             "AAA": [date(2015, 3, 3), date(2017, 10, 3)]})
        with self.assertRaises(FileNotFoundError):
            R.ex_dates(Path(tempfile.gettempdir()) / "no-such-actions.csv")

    def package(self, name, modules):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pkg = Path(d.name) / name
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        body = "NAME = {!r}\nVERSION = 1\nLOOKBACK = 5\nDEFAULTS = {{}}\ndef detect(bars, cfg):\n    return None\n"
        for file, plugin_name in modules.items():
            (pkg / f"{file}.py").write_text(body.format(plugin_name))
        sys.path.insert(0, d.name)
        self.addCleanup(sys.path.remove, d.name)
        return importlib.import_module(name)

    def test_discover(self):
        found = R.discover(self.package("fakepkg_ok", {"one": "first", "two": "second", "_helper": "hidden"}))
        self.assertEqual(sorted(found), ["first", "second"])
        self.assertEqual(found["first"].LOOKBACK, 5)
        with self.assertRaises(R.PluginContractError):
            R.discover(self.package("fakepkg_dup", {"one": "same", "two": "same"}))

    def test_the_real_package_loads(self):
        found = R.discover(patterns)
        self.assertEqual(sorted(found), sorted(p.NAME for p in found.values()))
        R.configure(found, R.CONFIG)  # the checked-in config, if any, must be valid

    @unittest.skipUnless(R.ACTIONS.exists(), "data/clean is local only")
    def test_real_actions_file(self):
        ex = R.ex_dates(R.ACTIONS)
        self.assertEqual(sum(map(len, ex.values())), 1556)
        self.assertEqual(max(d for ds in ex.values() for d in ds), date(2025, 10, 27))


if __name__ == "__main__":
    unittest.main()
