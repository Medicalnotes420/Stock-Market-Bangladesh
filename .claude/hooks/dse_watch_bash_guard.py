"""PreToolUse hook for the dse-watch agent: allow only the read-only commands its prompt lists.
A guardrail against slips, not a sandbox (the allowed scripts can still write their own outputs).
Reads the hook JSON on stdin; exit 2 blocks the call and the message goes back to the agent."""
import json
import re
import sys

ALLOWED = [
    r"python scripts/(watch_share|trade_plan|screen|read_pdf)\.py( .*)?",
    r"python -m unittest discover -s tests -t \.",
    r'(MSYS_NO_PATHCONV=1 )?schtasks /Query /TN "DSE Share Watch" /V /FO LIST',
    r"(ls|cat|head|tail|wc|grep|rg|date|pwd)( .*)?",
    r"git (status|diff|log|show)( .*)?",
]
BAD = re.compile(r"[;&<>`]|\$\(")  # chaining, redirects, substitution; pipes are checked per segment


def allowed(cmd):
    cmd = cmd.strip().replace("2>&1", "")  # merging stderr is harmless
    if not cmd or BAD.search(cmd):
        return False
    return all(any(re.fullmatch(p, seg.strip()) for p in ALLOWED) for seg in cmd.split("|"))


if __name__ == "__main__":
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    if not allowed(cmd):
        print(f"dse-watch is read-only: this command is not on its list: {cmd}", file=sys.stderr)
        sys.exit(2)
