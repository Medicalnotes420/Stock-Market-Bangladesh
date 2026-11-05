"""Print the text of a PDF (the auditor's reports saved in data/watch/auditor/). Read-only.

  python scripts/read_pdf.py data/watch/auditor/AL-HAJTEX25.pdf [--pages 5]"""
import argparse
import sys

from pypdf import PdfReader

ap = argparse.ArgumentParser()
ap.add_argument("pdf")
ap.add_argument("--pages", type=int, default=5, help="read at most this many pages")
a = ap.parse_args()
try:
    r = PdfReader(a.pdf)
except (OSError, ValueError) as e:
    sys.exit(f"cannot read {a.pdf}: {e}")
for i, p in enumerate(r.pages[:a.pages], 1):
    print(f"--- page {i} of {len(r.pages)} ---")
    print(p.extract_text() or "(no text on this page: a scanned image?)")
