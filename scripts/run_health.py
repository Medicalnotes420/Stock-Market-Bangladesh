"""Health of the daily "DSE Share Watch" task in one printout, so nobody has to eyeball the log:
the Windows task's Last Run Time / Last Result / settings, and the newest block of data/watch/run.log.

  python scripts/run_health.py

Exit code 1 when the task's Last Result is not 0 or the newest log block has a failure line."""
import subprocess
import sys
from pathlib import Path

TASK = "DSE Share Watch"
LOG = Path("data/watch/run.log")
WANT = ("Status", "Scheduled Task State", "Last Run Time", "Last Result", "Next Run Time", "Run As User",
        "Logon Mode", "Power Management")


def parse_schtasks(text):
    """{field: value} for the lines of `schtasks /Query /V /FO LIST` that we report."""
    out = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        if k.strip() in WANT and k.strip() not in out:
            out[k.strip()] = v.strip()
    return out


def last_block(log):
    """The text from the last line that starts with '====' to the end, or '' if there is none."""
    lines = log.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("====")]
    return "\n".join(lines[starts[-1]:]) if starts else ""


def summarise(task, block):
    """Plain lines: problems first, then the facts. Returns (lines, ok)."""
    problems, facts = [], []
    code = task.get("Last Result")
    if code is None:
        problems.append("PROBLEM: the task query returned no Last Result (task missing or schtasks failed)")
    elif code != "0":
        hexcode = f"0x{int(code) & 0xFFFFFFFF:08X}" if code.lstrip("-").isdigit() else code
        problems.append(f"PROBLEM: Last Result is {code} ({hexcode}), not 0: the task failed. Cause not known from this output")
    if not block:
        problems.append("PROBLEM: run.log has no run block at all")
    else:
        bad = [ln for ln in block.splitlines() if "FAILED" in ln]
        problems += [f"PROBLEM in newest log block: {ln}" for ln in bad]
        head = block.splitlines()[0]
        facts.append(f"Newest log block header: {head}")
        facts += [f"Log line: {ln}" for ln in block.splitlines() if " regime " in ln or ln.startswith("fetching")
                  or " sessions)" in ln]
    for k in WANT:
        if k in task:
            facts.append(f"Task {k}: {task[k] or '(blank: schtasks lists no condition here)'}")
    return problems + facts, not problems


def main():
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK, "/V", "/FO", "LIST"], capture_output=True, text=True)
    task = parse_schtasks(r.stdout)
    log = LOG.read_text(errors="replace") if LOG.exists() else ""
    lines, ok = summarise(task, last_block(log))
    print("\n".join(lines))
    print("Note: a failed block followed by a later block with a '(session ...)' header and a regime line means the"
          " rerun recovered. Header times are this PC's clock.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
