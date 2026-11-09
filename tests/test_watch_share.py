import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "watch_share.py"


class WatchShareFailureTest(unittest.TestCase):
    def test_all_shares_failing_keeps_the_old_page(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "page.html"
            out.write_text("last good page")
            r = subprocess.run([sys.executable, str(SCRIPT), "--csv", str(Path(d) / "missing.csv"), "--out", str(out)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(out.read_text(), "last good page")


if __name__ == "__main__":
    unittest.main()
