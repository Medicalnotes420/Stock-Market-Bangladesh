"""Runs the hand-labeled examples in tests/fixtures/chart/labeled.toml against the real price file
(docs/design/eod-chart-app.md 7.3). The reading and judging of examples is tested on made-up data, so
that part runs anywhere; the examples themselves need data/clean and are skipped without it."""
import tempfile
import tomllib
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from chartapp import bars as B, runner as R
from chartapp.labels import forward_outcome
from chartapp.patterns import Detection
from tests.test_chart_runner import make

LABELED = Path(__file__).parent / "fixtures" / "chart" / "labeled.toml"
PLUGINS = R.discover()
CONFIG = R.configure(PLUGINS, R.CONFIG)
_KEYS = {"fire": {"pattern", "ticker", "expect", "signal_date", "within", "note"},
         "none": {"pattern", "ticker", "expect", "from", "to", "note"}}
ENOUGH = 10  # "fire" examples of one pattern before the all-winners check applies
HORIZON = 20
# labels.py: no corporate action is inferred after the A2 data ends, so a later window can hold an unadjusted
# bonus that reads as a loss. Outcomes whose window ends after this day are left out of the all-winners check.
LABEL_UNTIL = date(2026, 1, 8)


def load(path):
    """(holdout_from, examples). Any mistake in the file is a ValueError naming the example."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    holdout, examples = data.pop("holdout_from", None), data.pop("example", [])
    if type(holdout) is not date or data or type(examples) is not list or any(type(e) is not dict for e in examples):
        raise ValueError(f"{path}: needs holdout_from = <date> and nothing else but [[example]] tables")
    for n, ex in enumerate(examples, 1):
        def bad(why):
            return ValueError(f"{path}: example {n} ({ex.get('ticker')}): {why}")
        kind = ex.get("expect")
        if kind not in _KEYS:
            raise bad('expect must be "fire" or "none"')
        if extra := set(ex) - _KEYS[kind]:
            raise bad(f"unknown keys {sorted(extra)} for a {kind!r} example")
        if ex.get("pattern") not in CONFIG:
            raise bad(f"pattern {ex.get('pattern')!r} is not an enabled plugin")
        if type(ex.get("ticker")) is not str or type(ex.get("note", "")) is not str:
            raise bad("ticker and note must be text")
        days = ("signal_date",) if kind == "fire" else ("from", "to")
        if any(type(ex.get(k)) is not date for k in days):
            raise bad(f"{' and '.join(days)} must be dates written as 2019-03-14, without quotes")
        if kind == "fire" and (type(ex.setdefault("within", 0)) is not int or ex["within"] < 0):
            raise bad("within must be a whole number of sessions, 0 or more")
        if kind == "none" and ex["from"] > ex["to"]:
            raise bad("from is after to")
    return holdout, examples


def when(ex):
    """The day that decides tuning or holdout: the last day the example covers."""
    return ex["signal_date"] if ex["expect"] == "fire" else ex["to"]


def verdict(ex, rows, signals, can_fire):
    """None if the plugin agrees with the example, else a sentence saying how it disagrees.
    `can_fire` is the set of days on which the runner lets a signal through at all."""
    fired = [s.signal_date for s in signals]
    if ex["expect"] == "none":
        inside = [str(d) for d in fired if ex["from"] <= d <= ex["to"]]
        if inside:
            return f"fired on {', '.join(inside)}"
        # an example that could not have failed proves nothing
        if not any(ex["from"] <= d <= ex["to"] for d in can_fire):
            return ("no day in this range could have fired: it is outside the ticker's history, or every "
                    "day is blocked by a gap flag or an ex-date")
        return None
    at = {r.date: i for i, r in enumerate(rows)}
    if ex["signal_date"] not in at:
        return f"{ex['signal_date']} is not a day {ex['ticker']} traded"
    i, w = at[ex["signal_date"]], ex["within"]
    first, last = rows[max(0, i - w)].date, rows[min(len(rows) - 1, i + w)].date  # sessions, not calendar days
    if any(first <= d <= last for d in fired):
        return None
    near = min(fired, key=lambda d: abs(d - ex["signal_date"]), default=None)
    blocked = "" if ex["signal_date"] in can_fire else (
        " (signals are blocked on this day: a gap flag or an ex-date is in its window, which the labeling "
        "view does not show)")
    return f"no signal within {w} sessions of {ex['signal_date']}; nearest is {near}{blocked}"


def _always(bars, cfg):
    return Detection("neutral")


def judge(examples, tickers=B.rows, actions=None):
    """[(example, complaint)] for every example the plugin disagrees with."""
    ex_dates = R.ex_dates(R.ACTIONS) if actions is None else actions
    signals, out = {}, []
    for ex in examples:
        key = (ex["ticker"], ex["pattern"])
        try:
            rows = tickers(ex["ticker"])
        except KeyError:
            out.append((ex, "no such ticker in the price file"))
            continue
        if key not in signals:
            plugin, ex_days = PLUGINS[key[1]], ex_dates.get(key[0], ())
            # the same windows through a plugin that always fires: the days left are the ones not blocked
            probe = SimpleNamespace(NAME="probe", VERSION=0, LOOKBACK=plugin.LOOKBACK, detect=_always)
            signals[key] = (R.run(plugin, CONFIG[key[1]], key[0], rows, ex_days),
                            {s.signal_date for s in R.run(probe, {}, key[0], rows, ex_days)})
        if complaint := verdict(ex, rows, *signals[key]):
            out.append((ex, complaint))
    return out


def report(failures):
    return "\n".join(f"  {ex['pattern']} {ex['ticker']} {when(ex)} expect {ex['expect']}: {why}"
                     + (f"  [{ex['note']}]" if ex.get("note") else "") for ex, why in failures)


class Harness(unittest.TestCase):
    """The reading and judging logic, on made-up data."""

    def file(self, body):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "labeled.toml"
        p.write_text("holdout_from = 2023-01-01\n" + body, encoding="utf-8")
        return p

    def test_reads_both_kinds(self):
        holdout, (a, b) = load(self.file(
            '[[example]]\npattern = "swing_breakout"\nticker = "AAA"\nsignal_date = 2019-03-14\nexpect = "fire"\n'
            '[[example]]\npattern = "swing_breakout"\nticker = "BBB"\nfrom = 2020-06-01\nto = 2020-08-31\n'
            'expect = "none"\nnote = "flat"\n'))
        self.assertEqual(holdout, date(2023, 1, 1))
        self.assertEqual((a["signal_date"], a["within"]), (date(2019, 3, 14), 0))
        self.assertEqual((b["from"], b["to"], b["note"]), (date(2020, 6, 1), date(2020, 8, 31), "flat"))

    def test_mistakes_are_named(self):
        head = '[[example]]\npattern = "swing_breakout"\nticker = "AAA"\n'
        for body in (head + 'signal_date = 2019-03-14\nexpect = "maybe"\n',
                     head + 'signal_date = "2019-03-14"\nexpect = "fire"\n',
                     head + 'expect = "fire"\n',
                     head + 'signal_date = 2019-03-14\nwithin = -1\nexpect = "fire"\n',
                     head + 'signal_date = 2019-03-14\nwithin = 1.5\nexpect = "fire"\n',
                     head + 'signal_date = 2019-03-14\nexpect = "fire"\nfrom = 2019-01-01\n',
                     head + 'from = 2020-08-31\nto = 2020-06-01\nexpect = "none"\n',
                     head + 'from = 2020-06-01\nexpect = "none"\n',
                     head + 'from = 2020-06-01\nto = 2020-08-31\nexpect = "none"\noutcome = "won"\n',
                     '[[example]]\npattern = "no_such"\nticker = "AAA"\nsignal_date = 2019-03-14\nexpect = "fire"\n',
                     'stray = 1\n', 'example = 1\n', 'example = [1]\n',
                     '[example]\npattern = "swing_breakout"\n'):  # one bracket: a table, not a list of them
            with self.assertRaisesRegex(ValueError, "labeled.toml", msg=body):
                load(self.file(body))
        with self.assertRaises(ValueError):  # no holdout_from
            p = self.file("")
            p.write_text("")
            load(p)

    def test_verdicts(self):
        rows = [r for r in make(600) if r.date.weekday() < 5]  # drop two days a week: sessions are not days
        name = "swing_breakout"
        signals = R.run(PLUGINS[name], CONFIG[name], "T", rows)
        at = {r.date: i for i, r in enumerate(rows)}
        where = [at[s.signal_date] for s in signals]
        # a signal with no other within 4 sessions and room either side, so each case below has one cause
        i = next(n for n in where if 4 < n < len(rows) - 4 and all(abs(m - n) > 4 for m in where if m != n))
        hit = rows[i].date

        open_days = {r.date for r in rows}

        def fire(day, within=0, can_fire=open_days):
            return verdict({"pattern": name, "ticker": "T", "expect": "fire", "signal_date": day, "within": within},
                           rows, signals, can_fire)

        def none(start, end, can_fire=open_days):
            return verdict({"pattern": name, "ticker": "T", "expect": "none", "from": start, "to": end},
                           rows, signals, can_fire)

        self.assertIsNone(fire(hit))
        self.assertIsNone(fire(rows[i - 2].date, within=2))  # two sessions early, allowed
        self.assertIsNone(fire(rows[i + 2].date, within=2))
        self.assertIn("no signal within 1 sessions", fire(rows[i - 2].date, within=1))
        self.assertIn(f"nearest is {hit}", fire(rows[i - 2].date, within=1))
        self.assertIn("is not a day T traded", fire(rows[i].date + timedelta(days=4000)))
        quiet_from, quiet_to = rows[i + 1].date, rows[i + 3].date
        self.assertIsNone(none(quiet_from, quiet_to))
        self.assertEqual(none(rows[i - 1].date, quiet_to), f"fired on {hit}")
        self.assertEqual(none(hit, hit), f"fired on {hit}")  # both ends are included
        # a "none" example that could not have failed is refused, not passed
        self.assertIn("no day in this range could have fired", none(date(1990, 1, 1), date(1990, 2, 1)))
        self.assertIn("no day in this range could have fired", none(quiet_from, quiet_to, can_fire=set()))
        self.assertIsNone(none(quiet_from, quiet_to, can_fire={quiet_to}))  # one open day is enough
        # a missed "fire" on a blocked day says so; on an open day it does not
        self.assertIn("signals are blocked on this day", fire(rows[i - 2].date, within=1, can_fire=set()))
        self.assertNotIn("blocked", fire(rows[i - 2].date, within=1))

    def test_holdout_goes_by_the_last_day_covered(self):
        self.assertEqual(when({"expect": "fire", "signal_date": date(2022, 6, 1)}), date(2022, 6, 1))
        self.assertEqual(when({"expect": "none", "from": date(2022, 6, 1), "to": date(2023, 6, 1)}), date(2023, 6, 1))

    def test_judge_sees_blocked_windows(self):
        rows = make(300, gaps={150})  # the flag blocks every window that holds bar 150
        name = "swing_breakout"
        day = lambda n: rows[n].date  # noqa: E731
        inside = {"pattern": name, "ticker": "T", "expect": "none", "from": day(150), "to": day(160)}
        partly = {"pattern": name, "ticker": "T", "expect": "none", "from": day(140), "to": day(160)}
        fire = {"pattern": name, "ticker": "T", "expect": "fire", "signal_date": day(155), "within": 0}
        got = dict((ex["expect"] + str(ex.get("from", "")), why)
                   for ex, why in judge([inside, partly, fire], tickers={"T": tuple(rows)}.__getitem__, actions={}))
        self.assertIn("no day in this range could have fired", got["none" + str(day(150))])
        self.assertIn("signals are blocked on this day", got["fire"])
        # `partly` reaches back to open days; it is only reported if the plugin really fired there
        self.assertTrue(got.get("none" + str(day(140)), "fired on").startswith("fired on"))

    def test_judge_and_report(self):
        rows = make(300)
        name = "swing_breakout"
        hit = R.run(PLUGINS[name], CONFIG[name], "T", rows)[1].signal_date
        good = {"pattern": name, "ticker": "T", "expect": "fire", "signal_date": hit, "within": 0}
        wrong = {"pattern": name, "ticker": "T", "expect": "none", "from": hit, "to": hit, "note": "looked flat"}
        missing = {**good, "ticker": "NOPE"}
        lookup = {"T": tuple(rows)}
        got = judge([good, wrong, missing], tickers=lookup.__getitem__, actions={})
        self.assertEqual([(ex["ticker"], ex["expect"]) for ex, _ in got], [("T", "none"), ("NOPE", "fire")])
        text = report(got)
        self.assertIn(f"swing_breakout T {hit} expect none: fired on {hit}  [looked flat]", text)
        self.assertIn("no such ticker", text)

    def test_the_checked_in_file_is_valid(self):
        holdout, examples = load(LABELED)
        self.assertIs(type(holdout), date)
        self.assertIsInstance(examples, list)


@unittest.skipUnless(B.PRICES.exists() and R.ACTIONS.exists(), "data/clean is local only")
class Labeled(unittest.TestCase):
    """The examples a person labeled, against the real data."""

    @classmethod
    def setUpClass(cls):
        cls.holdout, cls.examples = load(LABELED)
        if not cls.examples:
            raise unittest.SkipTest(f"no examples labeled yet in {LABELED.name}")

    def test_tuning_examples(self):
        failures = judge([ex for ex in self.examples if when(ex) < self.holdout])
        self.assertFalse(failures, "\n" + report(failures))

    def test_holdout_examples(self):
        failures = judge([ex for ex in self.examples if when(ex) >= self.holdout])
        self.assertFalse(failures, "\nholdout: do not tune the plugin to these\n" + report(failures))

    def test_fire_examples_are_not_all_winners(self):
        for name in CONFIG:
            outcomes = []
            for ex in self.examples:
                if ex["pattern"] != name or ex["expect"] != "fire":
                    continue
                rows = B.rows(ex["ticker"])
                i = next((n for n, r in enumerate(rows) if r.date == ex["signal_date"]), None)
                if i is None or i + HORIZON >= len(rows) or rows[i + HORIZON].date > LABEL_UNTIL:
                    continue
                if o := forward_outcome(rows[i + 1:], HORIZON, Decimal("10"), Decimal("5")):
                    outcomes.append(o.ret_pct)
            if len(outcomes) >= ENOUGH:
                self.assertTrue(any(r <= 0 for r in outcomes),
                                f"{name}: all {len(outcomes)} fire examples gained over the next {HORIZON} "
                                "sessions, which shape-only labeling would rarely produce. Label more examples "
                                "from the cut-off view without looking ahead. Do not go looking for ones that failed.")


if __name__ == "__main__":
    unittest.main()
