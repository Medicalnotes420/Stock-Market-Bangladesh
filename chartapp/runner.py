"""Runs pattern plugins walk-forward (docs/design/eod-chart-app.md 5).

No lookahead is by construction: for signal bar i a plugin is handed bars[i + 1 - LOOKBACK : i + 1] and
nothing else, so later bars are not reachable from it."""
import csv
import hashlib
import importlib
import pkgutil
import tomllib
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cache
from itertools import accumulate
from pathlib import Path
from types import MappingProxyType

from chartapp import bars as B
from chartapp import patterns
from chartapp.patterns import Detection, Point, Segment

CONFIG = Path(__file__).resolve().parents[1] / "config" / "patterns.toml"
ACTIONS = B.PRICES.with_name("actions.csv")
# build_clean accepts a corporate action only once 10 later sessions exist (infer_actions hold=10). In those
# sessions a same-day run would have shown a raw gap where today's file is smooth, so signals there are dropped.
EX_BLOCK = 10
_DIRECTIONS = ("bullish", "bearish", "neutral")
_PARAM_TYPES = (int, Decimal, bool, str)


class PluginContractError(Exception):
    """A plugin broke the contract in chartapp/patterns/__init__.py."""


@dataclass(frozen=True, slots=True)
class Signal:
    pattern: str
    version: int
    config_hash: str
    ticker: str
    signal_date: date
    detection: Detection


def _not_finite(value) -> bool:
    return type(value) is Decimal and not value.is_finite()  # TOML allows nan and inf


def _checked(plugin):
    for attr, kind in (("NAME", str), ("VERSION", int), ("LOOKBACK", int), ("DEFAULTS", dict)):
        if type(getattr(plugin, attr, None)) is not kind:
            raise PluginContractError(f"{plugin!r}: {attr} must be a {kind.__name__}")
    if plugin.LOOKBACK < 1 or not callable(getattr(plugin, "detect", None)):
        raise PluginContractError(f"{plugin.NAME}: needs LOOKBACK >= 1 and a detect(bars, cfg) function")
    for key, default in plugin.DEFAULTS.items():
        if key == "enabled" or type(default) not in _PARAM_TYPES or _not_finite(default):
            raise PluginContractError(f"{plugin.NAME}: bad default {key}={default!r}")
    return plugin


def discover(package=patterns) -> dict:
    """Every plugin module in the package, by NAME."""
    found = {}
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        plugin = _checked(importlib.import_module(f"{package.__name__}.{info.name}"))
        if plugin.NAME in found:
            raise PluginContractError(f"two plugins are named {plugin.NAME}")
        found[plugin.NAME] = plugin
    return found


def configure(plugins: Mapping, path: Path = CONFIG) -> dict[str, Mapping]:
    """Effective config of each enabled plugin: DEFAULTS overlaid with its table in the TOML file.
    A missing file or table means defaults. Unknown names, unknown keys and wrong types are errors."""
    # parse_float=Decimal: 0.5 in the file arrives as Decimal("0.5"), never as a float
    file = tomllib.loads(path.read_text(encoding="utf-8"), parse_float=Decimal) if path.exists() else {}
    if unknown := set(file) - set(plugins):
        raise ValueError(f"{path}: no such plugin: {sorted(unknown)}")
    out = {}
    for name, plugin in plugins.items():
        table = file.get(name, {})
        if type(table) is not dict:
            raise ValueError(f"{path}: {name} must be a [{name}] table, got {table!r}")
        table = dict(table)
        enabled = table.pop("enabled", True)
        if type(enabled) is not bool:
            raise ValueError(f"{path}: [{name}] enabled must be true or false")
        for key, value in table.items():
            if key not in plugin.DEFAULTS:
                raise ValueError(f"{path}: [{name}] has no parameter {key!r}")
            want = type(plugin.DEFAULTS[key])
            # `is`, not isinstance: bool is a subclass of int, so `left = true` would pass
            if _not_finite(value):
                raise ValueError(f"{path}: [{name}] {key} must be a finite number, got {value}")
            if type(value) is not want:
                hint = " (write it with a decimal point)" if want is Decimal and type(value) is int else ""
                raise ValueError(f"{path}: [{name}] {key} must be a {want.__name__}, got {value!r}{hint}")
        if enabled:
            out[name] = MappingProxyType({**plugin.DEFAULTS, **table})
    return out


def config_hash(cfg: Mapping) -> str:
    return hashlib.sha256(repr(sorted(cfg.items())).encode()).hexdigest()[:8]


@cache
def ex_dates(path: Path) -> dict[str, list[date]]:
    """Accepted corporate-action ex-dates per ticker, sorted. A missing file is an error, not 'no actions'."""
    out: dict[str, list[date]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["ticker"], []).append(date.fromisoformat(row["date"]))
    return {t: sorted(ds) for t, ds in out.items()}


def _check(plugin, d, window):
    def bad(why):
        return PluginContractError(f"{plugin.NAME} on {window[-1].date}: {why}")

    def number(what, v):  # NaN and Infinity are Decimals too, and would reach the API's JSON
        if type(v) is not Decimal or not v.is_finite():
            raise bad(f"{what} is {v!r}, not a finite Decimal")

    def text(what, v):
        if type(v) is not str:
            raise bad(f"{what} is {v!r}, not a str")

    if type(d) is not Detection:
        raise bad(f"detect returned {type(d).__name__}, not Detection or None")
    if d.direction not in _DIRECTIONS:
        raise bad(f"direction {d.direction!r}")
    # tuples, not any iterable: a generator would be used up here and stored empty
    if type(d.points) is not tuple or type(d.segments) is not tuple or not isinstance(d.levels, Mapping):
        raise bad("points and segments must be tuples and levels a mapping")
    text("note", d.note)
    points = list(d.points)
    for s in d.segments:
        if type(s) is not Segment:
            raise bad(f"segment is {s!r}, not a Segment")
        text("segment role", s.role)
        points += [s.start, s.end]
    dates = {b.date for b in window}
    for p in points:
        if type(p) is not Point:
            raise bad(f"point is {p!r}, not a Point")
        text("point role", p.role)
        if p.date not in dates:
            raise bad(f"point {p.role!r} dated {p.date} is not a bar the plugin was given")
        number(f"point {p.role!r} price", p.price)
    for name, value in d.levels.items():
        text("level name", name)
        number(f"level {name!r}", value)
    if d.score is not None:
        number("score", d.score)
        if not 0 <= d.score <= 1:
            raise bad(f"score {d.score} is outside 0 to 1")


def run(plugin, cfg: Mapping, ticker: str, rows: Sequence[B.Row], ex: Sequence[date] = ()) -> list[Signal]:
    """Signals of one plugin over one ticker's full history. `ex` is the ticker's sorted ex-dates.
    The plugin sees plain Bars; the flag columns and the action list only ever remove signals here."""
    view = B.bars(tuple(rows))
    gaps = [0, *accumulate(r.gap_flag for r in rows)]  # gaps[j] = flagged bars before index j
    digest, out = config_hash(cfg), []
    for i in range(len(rows)):
        start = max(0, i + 1 - plugin.LOOKBACK)
        if gaps[i + 1] - gaps[start]:
            continue  # an unexplained limit-breaking move is inside the window
        recent = bisect_left(ex, rows[max(start, i + 1 - EX_BLOCK)].date)
        if recent < len(ex) and ex[recent] <= rows[i].date:
            continue  # an ex-date in the last EX_BLOCK bars
        window = view[start:i + 1]
        d = plugin.detect(window, cfg)
        if d is None:
            continue
        _check(plugin, d, window)
        out.append(Signal(plugin.NAME, plugin.VERSION, digest, ticker, rows[i].date, d))
    return out
