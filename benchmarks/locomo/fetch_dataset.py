"""Fetch the LoCoMo dataset (not redistributed here).

Source: https://github.com/snap-research/locomo (Snap Research, ACL 2024).
Both benchmark scripts call `ensure_dataset()` before reading it.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
DEST = Path(__file__).with_name("locomo10.json")


def ensure_dataset(dest: Path = DEST) -> Path:
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    print(f"downloading LoCoMo dataset -> {dest}", file=sys.stderr)
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlopen(URL, timeout=120)  # fail fast on network problems
    with urllib.request.urlopen(URL, timeout=300) as r, dest.open("wb") as fh:
        fh.write(r.read())
    print(f"downloaded {dest.stat().st_size // 1024} KiB", file=sys.stderr)
    return dest


if __name__ == "__main__":
    ensure_dataset()
