#!/usr/bin/env python3
"""Remove trailing full stops from description fields in JSONL word list files."""

import json
import sys
from pathlib import Path


def strip_trailing_period(s: str) -> str:
    if s and s.endswith("."):
        return s[:-1]
    return s


def process_file(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = 0
    out = []
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        entry = json.loads(line)
        desc = entry.get("description")
        if desc and desc.endswith("."):
            entry["description"] = strip_trailing_period(desc)
            changed += 1
        out.append(json.dumps(entry, ensure_ascii=False))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def main():
    root = Path(__file__).parent.parent
    files = [
        root / "wordlist_accepted.jsonl",
        root / "wordlist_uncertain.jsonl",
    ]
    for f in files:
        if not f.exists():
            print(f"Skipping {f} (not found)")
            continue
        n = process_file(f)
        print(f"{f.name}: {n} descriptions updated")


if __name__ == "__main__":
    main()
