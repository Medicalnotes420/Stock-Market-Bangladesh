"""Deposit rates and the share index, exactly as docs/DEPOSIT_RATES_PREREG.md.
Run from the repo root (after scripts/rates_vs_index.py has cached the IMF data):
    python -W ignore scripts/deposit_rates.py
Output: results/deposit_rates.csv (every test and check) and a printed verdict."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calendar_events import spearman_perm  # noqa: E402
from rates_signal import by_start, samples  # noqa: E402
from rates_vs_index import RAW, parse  # noqa: E402

P_BAR, P_WEAK, H = 0.0125, 0.05, 6
SPLIT_YEAR = 2011  # yearly halves: 1998-2011 and 2012-2025
NO_CAP = (pd.Period("2020-01", "M"), pd.Period("2021-12", "M"))
SERIES = {"MFS135_RT_PT_A_PT": "deposit", "S13BOND_RT_PT_A_PT": "bond_yield"}


def together(m, h, col):
    """Change in `col` over h months vs DSEX change over the same h months (rows t)."""
    return pd.DataFrame({"signal": m[col] - m[col].shift(h), "outcome": m.dsex / m.dsex.shift(h) - 1}).dropna()


def yearly_tests(y):
    """y: DataFrame by year [deposit (yearly avg), ret (share return %), inflation]. P1, P2, halves, real rate."""
    ch = y.deposit.diff()
    out = {}
    s = pd.concat([ch, y.ret], axis=1).dropna()
    out["P1"] = spearman_perm(s.iloc[:, 0], s.iloc[:, 1]) + (len(s),)
    s = pd.concat([ch.shift(1), y.ret], axis=1).dropna()
    out["P2"] = spearman_perm(s.iloc[:, 0], s.iloc[:, 1]) + (len(s),)
    for name, sel in (("P1 1998-2011", y.index <= SPLIT_YEAR), ("P1 2012-2025", y.index > SPLIT_YEAR)):
        s = pd.concat([ch[sel], y.ret[sel]], axis=1).dropna()
        out[name] = spearman_perm(s.iloc[:, 0], s.iloc[:, 1]) + (len(s),)
    real = (y.deposit - y.inflation).shift(1)
    s = pd.concat([real, y.ret], axis=1).dropna()
    out["S1 real rate -> next year"] = spearman_perm(s.iloc[:, 0], s.iloc[:, 1]) + (len(s),)
    return out


def starts(d, h=H):
    """Every non-overlapping start: (median rho, median p, all negative, n per start)."""
    r = by_start(d, h)
    return r.rho.median(), r.p.median(), bool((r.rho < 0).all()), int(r.n.min())


def residual(m, h):
    """Part of the h-month deposit-rate change not explained by the bond-yield change (least squares)."""
    x = pd.DataFrame({"dep": m.deposit - m.deposit.shift(h), "bond": m.bond_yield - m.bond_yield.shift(h)}).dropna()
    b = np.polyfit(x.bond, x.dep, 1)
    return (x.dep - np.polyval(b, x.bond)).rename("deposit_resid")


def best_p(res, ids):
    """Smallest p among the tests that came out negative (6-month tests: every start negative)."""
    return min((res[i]["p"] for i in ids if res[i]["rho"] < 0 and res[i]["all_negative"] is not False), default=1.0)


def verdicts(res):
    tog, lead = best_p(res, ["P1", "P3"]), best_p(res, ["P2", "P4"])
    halves = res["P1 1998-2011"]["rho"] < 0 and res["P1 2012-2025"]["rho"] < 0
    no_floor = res["P4 no floor"]["rho"] < 0 and res["P4 no floor"]["all_negative"]
    v_t = "ASSOCIATION EXISTS" if tog < P_BAR and halves else "WEAK" if tog < P_WEAK else "NONE"
    v_l = "PREDICTS" if lead < P_BAR and no_floor else "WEAK" if lead < P_WEAK else "NONE"
    return v_t, v_l


if __name__ == "__main__":
    rates = parse(RAW.read_text(encoding="utf-8"), SERIES)
    wb = pd.read_csv("results/dse_long_run.csv").set_index("year")
    y = rates.groupby(rates.index.year).mean()[["deposit"]].join(
        wb.rename(columns={"return_bdt_pct": "ret", "inflation_pct": "inflation"})[["ret", "inflation"]], how="inner")
    y = y[(y.index >= 1997) & (y.index <= 2025)]
    res = {k: {"rho": v[0], "p": v[1], "n": v[2], "all_negative": None} for k, v in yearly_tests(y).items()}

    s = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date").dsex.dropna()
    m = rates.join(s.groupby(s.index.to_period("M")).last().rename("dsex"), how="inner")
    m = m[m.index >= pd.Period("2012-10", "M")]
    lead = samples(m, H, "deposit")
    tog = together(m, H, "deposit")
    rev = pd.DataFrame({"signal": m.dsex / m.dsex.shift(H) - 1,
                        "outcome": m.deposit.shift(-H) - m.deposit}).dropna()
    mr = m.join(residual(m, H), how="inner")
    no_cap = ~((lead.index >= NO_CAP[0]) & (lead.index <= NO_CAP[1]))
    for name, d in {"P3": tog, "P4": lead, "P4 no floor": lead[lead.floor_share <= 0.5], "P4 no 2020-21": lead[no_cap],
                    "S2 reverse: DSEX -> deposit": rev,
                    "S3 P3 beyond bond yield": pd.DataFrame({"signal": mr.deposit_resid,
                                                             "outcome": m.dsex / m.dsex.shift(H) - 1}).dropna(),
                    "S3 P4 beyond bond yield": pd.DataFrame({"signal": mr.deposit_resid,
                                                             "outcome": m.dsex.shift(-H) / m.dsex - 1}).dropna()}.items():
        rho, p, neg, n = starts(d)
        res[name] = {"rho": rho, "p": p, "n": n, "all_negative": neg}
    yc = y.deposit.diff()
    rise, fall = y.ret[yc > 0], y.ret[yc <= 0]
    v_t, v_l = verdicts(res)
    out = pd.DataFrame(res).T
    Path("results").mkdir(exist_ok=True)
    out.to_csv("results/deposit_rates.csv", index_label="test")
    pd.set_option("display.width", 200)
    print(out.astype({"rho": float, "p": float}).round(3).to_string())
    print(f"\nYears deposit rates rose: shares {rise.mean():+.1f}% (median {rise.median():+.1f}%, n={len(rise)}); "
          f"fell or flat: {fall.mean():+.1f}% (median {fall.median():+.1f}%, n={len(fall)})")
    print(f"Deposit vs bond yield, monthly levels from 2012-10: correlation {m.deposit.corr(m.bond_yield):.2f}")
    print(f"Verdict, move together: {v_t}")
    print(f"Verdict, predicts: {v_l}")
