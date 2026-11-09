"""PreToolUse hook for the dse-watch agent: allow only the read-only commands its prompt lists, and keep it
out of its own answer key (docs/AGENT_CHECKS.md) in Bash, Read and Grep.
A guardrail against slips, not a sandbox (the allowed scripts can still write their own outputs).
Reads the hook JSON on stdin; exit 2 blocks the call and the message goes back to the agent."""
import json
import re
import sys

ARG = r"( [A-Za-z0-9_.][\w./-]*)+"  # plain values only: a token starting with "-" could be an abbreviated --out
ALLOWED = [
    # the one-off page only: without --symbols/--csv, or with another --out, it would rewrite watch.html and
    # append to the real forecast_log.csv
    rf"python scripts/watch_share\.py --(symbols|csv){ARG}( --(above|below) [\d.]+)* --out data/watch/one_off\.html",
    r"python scripts/(trade_plan|screen|read_pdf|run_health|short_answer)\.py( .*)?",
    r"python -m unittest discover -s tests -t \.",
    r'(MSYS_NO_PATHCONV=1 )?schtasks /Query /TN "DSE Share Watch" /V /FO LIST',
    r"(ls|cat|head|tail|wc|grep|rg|date|pwd)( .*)?",
    r"git (status|diff|log|show)( .*)?",
]
BAD = re.compile(r"[;&<>`]|\$\(")  # chaining, redirects, substitution; pipes are checked per segment


def answer_key(text):
    # shortcut: matches the file name only, so `cat docs/*` or a Grep over docs/ still reaches it;
    # move the file out of the repo if that ever shows up in a run
    return "agent_checks" in text.lower()


def allowed(cmd):
    cmd = cmd.strip().replace("2>&1", "")  # merging stderr is harmless
    if not cmd or BAD.search(cmd) or answer_key(cmd):
        return False
    return all(any(re.fullmatch(p, seg.strip()) for p in ALLOWED) for seg in cmd.split("|"))


if __name__ == "__main__":
    d = json.load(sys.stdin)
    ti = d.get("tool_input", {})
    if d.get("tool_name", "Bash") == "Bash":
        if not allowed(ti.get("command", "")):
            print(f"dse-watch is read-only: this command is not on its list: {ti.get('command', '')}", file=sys.stderr)
            sys.exit(2)
    elif answer_key(" ".join(str(ti.get(k, "")) for k in ("file_path", "path", "glob"))):
        print("dse-watch may not read docs/AGENT_CHECKS.md (its own answer key)", file=sys.stderr)
        sys.exit(2)
