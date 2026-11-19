"""JEV: path selection, the 2-error retry gate and the quant-file reminder.
Runs on PreToolUse (*), PostToolUse (edits and shell only) and PostToolUseFailure (*).
Exit 2 blocks; stderr goes back to the model. A bad payload is a no-op, never a crash."""
import json
import os
import pathlib
import sys

try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
ev, tool, inp = d.get("hook_event_name", ""), d.get("tool_name", ""), d.get("tool_input") or {}
sid = d.get("session_id", "s")
ROOT = pathlib.Path(__file__).resolve().parents[2]
ALLOWED = [ROOT, pathlib.Path("C:/Users/WALTON/.claude/projects"), pathlib.Path("C:/Users/WALTON/AppData/Local/Temp/claude")]
QUANT = {"async_risk_guard.py", "dse_paper_harness.py", "test_async_risk_guard.py", "test_quant_verifier_dse.py"}
WRITES = ("sed -i", " > ", ">>", "tee ", "Set-Content", "Out-File", "Add-Content", "mv ", "cp ", "rm ",
          "Move-Item", "Copy-Item", "Remove-Item", "git checkout", "git restore", "git apply", "patch ")
state = ROOT / ".claude/state/jev_errors.json"
try:
    errs = json.loads(state.read_text())
except (OSError, ValueError):
    errs = {}
k = f"{sid}:{tool}"


def save():
    # keep only nonzero counts, so the file stays tiny; replace atomically
    keep = {x: v for x, v in errs.items() if v}
    state.parent.mkdir(parents=True, exist_ok=True)
    tmp = state.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(keep))
    os.replace(tmp, state)


def block(msg):
    print(f"JEV: {msg}", file=sys.stderr)
    sys.exit(2)


if ev in ("PostToolUse", "PostToolUseFailure"):
    # shortcut: PostToolUse only fires for edit/shell tools, so other tools' failures count
    # since the last block, not consecutively; widen the matcher if that gets noisy
    old = errs.get(k, 0)
    errs[k] = old + 1 if ev == "PostToolUseFailure" else 0
    if errs[k] != old:
        save()
    if ev == "PostToolUse":
        if tool in ("Write", "Edit", "NotebookEdit"):
            name = pathlib.Path(inp.get("file_path") or inp.get("notebook_path") or "").name
            hit = name if name in QUANT else None
        else:
            # shortcut: a shell command counts as a quant change only if it names a quant file
            # and looks like a write; extend WRITES if a new edit idiom slips through
            cmd = inp.get("command", "")
            hit = next((q for q in QUANT if q in cmd), None) if any(w in cmd for w in WRITES) else None
        if hit:  # exit 2 so the reminder reaches the model; the change has already happened
            block(f"touched core quant file {hit}. Before marking the task done, run the quant-verifier "
                  "subagent and `python -m pytest test_async_risk_guard.py test_quant_verifier_dse.py`.")
    sys.exit(0)

if errs.get(k, 0) >= 2:  # retry gate
    errs[k] = 0  # allow one attempt after the model has been told to consult the advisor
    save()
    block(f"{tool} failed twice. Consult the advisor before retrying.")

p = inp.get("file_path", "")
if tool in ("Write", "Edit") and p and not any(pathlib.Path(p).resolve().is_relative_to(r.resolve()) for r in ALLOWED):  # path selection
    block("writes are limited to the project, the memory folder and the scratchpad.")
