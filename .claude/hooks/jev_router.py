"""JEV: deterministic routing for tool choice, path selection and the 2-error retry gate.
Runs on PreToolUse, PostToolUse and PostToolUseFailure. Exit 2 blocks; stderr goes back to the model."""
import json
import pathlib
import re
import sys

d = json.load(sys.stdin)
ev, tool, inp = d["hook_event_name"], d.get("tool_name", ""), d.get("tool_input", {})
ROOT = pathlib.Path("E:/AI Apps/Stockapp")
ALLOWED = [ROOT, pathlib.Path("C:/Users/WALTON/.claude/projects"), pathlib.Path("C:/Users/WALTON/AppData/Local/Temp/claude")]
QUANT = {"async_risk_guard.py", "dse_paper_harness.py", "test_async_risk_guard.py", "test_quant_verifier_dse.py"}
state = ROOT / ".claude/state/jev_errors.json"
try:
    errs = json.loads(state.read_text())
except (OSError, ValueError):
    errs = {}
k = f"{d.get('session_id', 's')}:{tool}"


def block(msg):
    print(f"JEV: {msg}", file=sys.stderr)
    sys.exit(2)


if ev in ("PostToolUse", "PostToolUseFailure"):  # failure counts up, a success resets
    errs[k] = errs.get(k, 0) + 1 if ev == "PostToolUseFailure" else 0
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(errs))
    name = pathlib.Path(inp.get("file_path", "")).name
    if ev == "PostToolUse" and tool in ("Write", "Edit") and name in QUANT:
        # exit 2 so the reminder reaches the model; the edit has already happened
        block(f"edited core quant file {name}. Before marking the task done, run the quant-verifier "
              "subagent and `pytest test_async_risk_guard.py test_quant_verifier_dse.py --asyncio-mode=strict`.")
    sys.exit(0)

if errs.get(k, 0) >= 2:  # retry gate
    errs[k] = 0  # allow one attempt after the model has been told to consult the advisor
    state.write_text(json.dumps(errs))
    block(f"{tool} failed twice. Consult the advisor before retrying.")

if tool == "Bash" and re.match(r"\s*(grep|rg|find|cat)\b", inp.get("command", "")):  # tool choice
    block("use Grep, Glob or Read instead of shell grep/find/cat.")

p = inp.get("file_path", "")
if tool in ("Write", "Edit") and p and not any(pathlib.Path(p).resolve().is_relative_to(r.resolve()) for r in ALLOWED):  # path selection
    block("writes are limited to the project, the memory folder and the scratchpad.")
