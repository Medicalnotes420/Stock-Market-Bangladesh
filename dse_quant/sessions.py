"""DSE trading calendar: which days are sessions. Weekend days, holidays and make-up sessions come from
config/workflow.toml ([calendar]); nothing here is derived at run time."""
import tomllib
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import pandas as pd

CONFIG = Path(__file__).resolve().parents[1] / "config" / "workflow.toml"


@cache
def _calendar():
    c = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["calendar"]
    for k in ("holidays", "extra_sessions"):  # a quoted date would never match and silently count as a session
        if not all(type(d) is date for d in c[k]):
            raise ValueError(f"{CONFIG}: [calendar] {k} must be unquoted dates like 2026-12-16")
    return frozenset(c["weekend_days"]), frozenset(c["holidays"]), frozenset(c["extra_sessions"])


def closed_reason(day):
    """None if `day` is a DSE session, else "dse_weekend" or "market_closed" (a listed holiday)."""
    weekend, holidays, extra = _calendar()
    d = pd.Timestamp(day).date()
    if d in extra:
        return None
    if d.weekday() in weekend:
        return "dse_weekend"
    return "market_closed" if d in holidays else None


def expected_session(asof):
    """The latest session on or before `asof`: the bar a run as of that day should already hold."""
    d = pd.Timestamp(asof).date()
    while closed_reason(d):
        d -= timedelta(days=1)
    return d
