import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / ".claude" / "hooks" / "dse_watch_bash_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTest(unittest.TestCase):
    def test_commands_the_agent_prompt_lists_are_allowed(self):
        for c in ['python scripts/screen.py --sector Cement --top 30',
                  'python scripts/watch_share.py --symbols CROWNCEMNT --out data/watch/one_off.html',
                  'python scripts/read_pdf.py data/watch/auditor/AL-HAJTEX25.pdf --pages 2',
                  'MSYS_NO_PATHCONV=1 schtasks /Query /TN "DSE Share Watch" /V /FO LIST',
                  'python -m unittest discover -s tests -t .',
                  'tail -40 data/watch/run.log', 'git diff --stat watchlist.txt',
                  'python scripts/screen.py --max-pe 10 2>&1 | head -20']:
            self.assertTrue(guard.allowed(c), c)

    def test_writes_and_other_commands_are_blocked(self):
        for c in ['echo x > watchlist.txt', 'rm -rf data', 'python -c "print(1)"', 'sed -i s/a/b/ watchlist.txt',
                  'git commit -am x', 'ls; rm x', 'cat x && rm x', 'ls $(rm x)', 'python scripts/paper_run.py',
                  'python scripts/screen.py | tee out.txt', '']:
            self.assertFalse(guard.allowed(c), c)


if __name__ == "__main__":
    unittest.main()
