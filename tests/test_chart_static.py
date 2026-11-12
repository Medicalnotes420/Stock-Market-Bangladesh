"""Static rules for chartapp/ (docs/design/eod-chart-app.md 7.2). A cheap second guard: it cannot see every
float (for example `/` between two ints), so the no-float-in-JSON API test stays the real one.
It is strict on purpose: even `isinstance(v, float)` is flagged."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "chartapp"
BANNED = {"statistics", "math", "numpy", "anthropic", "requests", "httpx", "socket", "urllib.request"}
NO_LABELS = {"api.py", "runner.py", "geometry.py"}  # plus everything under patterns/


def imports(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            yield from (a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            mod = "." * n.level + (n.module or "")
            yield mod
            yield from (f"{mod}.{a.name}".replace("..", ".") for a in n.names)


def problems(path, tree):
    rel = path.relative_to(ROOT).as_posix()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id == "float":
            yield f"{rel}:{n.lineno} uses float"
        if isinstance(n, ast.Attribute) and n.attr.startswith("float"):  # np.float64, builtins.float
            yield f"{rel}:{n.lineno} uses float"
        if isinstance(n, ast.alias) and n.name == "float":  # from builtins import float as F
            yield f"{rel}:{n.lineno} uses float"
        if isinstance(n, ast.Constant) and type(n.value) is float:
            yield f"{rel}:{n.lineno} float literal {n.value!r}"
        if isinstance(n, ast.Constant) and n.value in ("float", "float32", "float64"):  # astype("float")
            yield f"{rel}:{n.lineno} float dtype string"
    for name in imports(tree):
        if any(name == b or name.startswith(b + ".") for b in BANNED):
            yield f"{rel} imports {name}"
        if (rel in NO_LABELS or rel.startswith("patterns/")) and name.split(".")[-1] == "labels":
            yield f"{rel} imports labels"


class StaticRules(unittest.TestCase):
    def test_chartapp_is_clean(self):
        files = sorted(ROOT.rglob("*.py"))
        self.assertTrue(files)
        found = [p for f in files for p in problems(f, ast.parse(f.read_text(encoding="utf-8")))]
        self.assertEqual(found, [])

    def test_the_scan_catches_each_rule(self):
        cases = {
            "x = float('1')": "uses float",
            "x = 0.5": "float literal",
            "x = np.float64(1)": "uses float",
            "x = builtins.float('1')": "uses float",
            "from builtins import float as F": "uses float",
            "df = df.astype('float')": "float dtype string",
            "import math": "imports math",
            "import numpy as np": "imports numpy",
            "import anthropic": "imports anthropic",
            "from urllib import request": "imports urllib.request",
            "import urllib.request": "imports urllib.request",
            "from statistics import mean": "imports statistics",
            "from . import labels": "imports labels",
            "from chartapp.labels import forward_outcome": "imports labels",
        }
        for src, want in cases.items():
            got = list(problems(ROOT / "runner.py", ast.parse(src)))
            self.assertTrue(any(want in g for g in got), (src, got))


if __name__ == "__main__":
    unittest.main()
