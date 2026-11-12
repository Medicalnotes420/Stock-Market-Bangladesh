"""Pattern plugins: one module per pattern in this package (docs/design/eod-chart-app.md 5).

A plugin module defines:
    NAME      str, unique
    VERSION   int, bumped when the detection logic changes
    LOOKBACK  int, the most bars it needs; the runner never passes more
    DEFAULTS  dict of parameter -> default (int, Decimal, bool or str)
    detect(bars, cfg) -> Detection | None    "does a signal fire on bars[-1]?"

Rules: fire only on the bar where the condition first becomes true; pure (no I/O, no state); Decimal only;
thresholds are ratios or percentages, never BDT amounts; every Point date is a date in `bars`.
Modules whose name starts with "_" are not loaded as plugins."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class Point:
    date: date
    price: Decimal
    role: str


@dataclass(frozen=True, slots=True)
class Segment:
    start: Point
    end: Point
    role: str


@dataclass(frozen=True, slots=True)
class Detection:
    direction: Literal["bullish", "bearish", "neutral"]
    points: tuple[Point, ...] = ()
    segments: tuple[Segment, ...] = ()
    levels: Mapping[str, Decimal] = field(default_factory=dict)
    score: Decimal | None = None  # 0 to 1, plugin-defined shape quality; not a probability
    note: str = ""
