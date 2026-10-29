"""Walk-forward stitching: join each year's returns from the parameter set chosen for that year."""
import pandas as pd

from dse_quant.backtest.costs import BASE


def switch_cost(mult=1.0, floor=0.001):
    """Selling the whole book and buying a new one: two sides at the minimum per-side cost."""
    return 2 * mult * (BASE + floor)


def stitch(year_returns, chosen, cost):
    """year_returns[y]: daily returns in year y of the run chosen for y. When the choice changes from
    the previous year, the first day pays `cost` for rotating the portfolio. Returns (series, switches)."""
    parts, switches, prev = [], 0, None
    for y in sorted(year_returns):
        r = year_returns[y].copy()
        if prev is not None and chosen[y] != prev and len(r):
            r.iloc[0] = (1 + r.iloc[0]) * (1 - cost) - 1
            switches += 1
        parts.append(r)
        prev = chosen[y]
    return pd.concat(parts), switches
