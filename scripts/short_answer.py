"""The finished short answer for one share, printed from the facts file so the agent quotes it instead of laying it out.

  python scripts/short_answer.py AL-HAJTEX              # from data/watch/facts.json (the daily run)
  python scripts/short_answer.py CROWNCEMNT --oneoff    # from data/watch/one_off_facts.json (after the one-off check)
  python scripts/short_answer.py CROWNCEMNT --oneoff --stock   # adds the fundamentals lines

Prints at most 9 lines (status) or 12 (--stock). Fields the file does not have are named, never guessed."""
import json
import sys
from pathlib import Path

DAILY = Path("data/watch/facts.json")
ONEOFF = Path("data/watch/one_off_facts.json")
MOVES = ("1d", "5d", "20d", "60d")


def lines(code, s, stock=False):
    """The answer lines for one share's facts dict `s`."""
    out = []
    if "trend" in s:
        mv = s.get("moves_pct", {})
        moves = " ".join(f"{k} {mv[k]:+g}%" for k in MOVES if k in mv)
        out.append(f"{code} closed Tk {s['close']:g} on {s['bar_date']}, trend {s['trend']}; {moves}; RSI {s.get('rsi', '?')}; "
                   f"support Tk {s.get('support_20d', '?')} / resistance Tk {s.get('resistance_20d', '?')}.")
        alerts = "; ".join(s.get("alerts_fired") or []) or "none"
        out.append(f"Alerts: {alerts}.")
        for f in s.get("rule_flags", []):
            out.append(f"Rule flag {f['flag'].split(':')[0]}: {f['verdict']}.")
    else:
        out.append(f"{code} closed Tk {s['close']:g} on {s['bar_date']}. Trend, moves, RSI and flags are not in this file yet: "
                   "take them from watch.html.")
    r = s.get("ranges_80pct")
    if r:
        a, b = r["5_sessions"], r["20_sessions"]
        out.append(f"Checked ranges: 5 sessions Tk {a['low']:g}-{a['high']:g} (middle {a['mid']:g}); "
                   f"20 sessions Tk {b['low']:g}-{b['high']:g} (middle {b['mid']:g}).")
    else:
        out.append("Checked ranges: not in this file yet; take them from watch.html.")
    trust = []
    d = s.get("dividend_ahead")
    if d:
        trust.append(f"dividend Tk {d['tk_per_share']:g} (record {d['record_date']}, {d['sessions_away']} sessions away; "
                     f"20-session range lowered {d['range_lowered_pct']:g}%)")
    if s.get("median_turnover_60d_mn") is not None and s["median_turnover_60d_mn"] < s.get("tested_shares_min_turnover_mn", 0):
        trust.append(f"less tested here: median turnover Tk {s['median_turnover_60d_mn']:g} mn vs Tk "
                     f"{s['tested_shares_min_turnover_mn']:g} mn tested")
    if not s.get("track_record"):
        trust.append("no scored track record yet")
    if trust:
        out.append("Trust less: " + "; ".join(trust) + ".")
    q = s.get("latest_quarter")
    if q:
        label = q.get("fiscal_quarter") or "latest period, no quarter label"
        out.append(f"Latest results: {label} EPS Tk {q['eps']:g}.")
    if stock and "eps" in s:
        yld = f"{100 * d['tk_per_share'] / s['close']:.1f}%" if d else "n/a"
        roe = f"{100 * s['eps'] / s['nav']:.1f}%" if s.get("nav") else "n/a"
        out.append(f"EPS Tk {s['eps']:g}, {s['eps_period']}; NAV Tk {s['nav']:g}, {s['nav_period']}; "
                   f"P/E {s['pe']:.1f}; Price/NAV {s['pb']:.2f}; ROE {roe}; dividend yield {yld}.")
        out.append("Not in this file: loans/equity, sector ranks, shareholding, auditor, EPS history - take at most "
                   "a line each from one_off.html.")
    return out


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    path = ONEOFF if "--oneoff" in argv else DAILY
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read {path}: {e}")
        return 1
    code = args[0].upper()
    s = data.get("shares", {}).get(code)
    if s is None:
        print(f"{code} is not in {path} (built {data.get('built')}); run the one-off check first.")
        return 1
    print(f"(from {path}, built {data.get('built')})")
    print("\n".join(lines(code, s, "--stock" in argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
