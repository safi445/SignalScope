from __future__ import annotations

import csv
import os
import sys
import urllib.request


IEEE_OUI_CSV_URL = "https://standards-oui.ieee.org/oui/oui.csv"


def main() -> int:
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir = os.path.join(root, "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "oui.csv")

    print(f"Downloading IEEE OUI CSV to: {out_path}")
    with urllib.request.urlopen(IEEE_OUI_CSV_URL, timeout=30) as r:
        content = r.read()

    # Basic sanity: ensure it parses as CSV and has expected header.
    text = content.decode("utf-8", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    if not rows or (rows[0] and rows[0][0].strip().lower() != "assignment"):
        print("Warning: unexpected CSV header; saving anyway.")

    with open(out_path, "wb") as f:
        f.write(content)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

