"""
Extract inflected word forms from the Kaikki Wiktionary JSONL dump.

Reads the already-downloaded raw-wiktextract-data.jsonl.gz from the
wiktionary raw directory and extracts all 'forms' entries for German entries
(lang_code == 'de'). These are inflected forms (conjugations, declensions)
that are not listed as standalone headwords.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

VALID_WORD = re.compile(r"^[a-zA-ZäöüÄÖÜß]{2,15}$")


def download(raw_dir: Path) -> Path:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "words.txt"

    archive = raw_dir.parent / "wiktionary" / "raw-wiktextract-data.jsonl.gz"
    if not archive.exists():
        print(f"  Warning: Kaikki archive not found at {archive}. Writing empty file.")
        out_file.write_text("", encoding="utf-8")
        return out_file

    forms: set[str] = set()
    with gzip.open(archive, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("lang_code") != "de":
                continue
            for fm in obj.get("forms", []):
                form = fm.get("form", "")
                if form and VALID_WORD.match(form):
                    forms.add(form.lower())

    words_sorted = sorted(forms)
    out_file.write_text("\n".join(words_sorted) + "\n", encoding="utf-8")
    print(f"  -> {len(words_sorted)} Kaikki forms written to {out_file}")
    return out_file
