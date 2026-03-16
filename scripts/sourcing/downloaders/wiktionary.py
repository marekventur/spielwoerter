"""
Download German Wiktionary headwords from Kaikki.org (Wiktextract JSONL).
One word per line in output; preserves headword as our canonical form.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import requests

KAIKKI_DEWIKTIONARY_JSONL_GZ = (
    "https://kaikki.org/dewiktionary/raw-wiktextract-data.jsonl.gz"
)


def download(raw_dir: Path) -> Path:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "headwords.txt"

    archive = raw_dir / "raw-wiktextract-data.jsonl.gz"
    if not archive.exists():
        r = requests.get(KAIKKI_DEWIKTIONARY_JSONL_GZ, stream=True)
        r.raise_for_status()
        with open(archive, "wb") as f:
            for chunk in r.iter_content(chunk_size=2**20):
                if chunk:
                    f.write(chunk)

    # German word chars (incl. umlauts and ß)
    word_re = re.compile(r"^[a-zA-ZäöüÄÖÜß\-]+$")

    seen = set()
    count = 0
    with gzip.open(archive, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            word = obj.get("word")
            if not word or not isinstance(word, str):
                continue
            # German Wiktionary: headwords are mostly German; we take all for max coverage
            # Normalize: strip spaces
            word = word.strip()
            if not word_re.match(word):
                continue
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            count += 1

    with open(out_file, "w", encoding="utf-8") as f:
        for w in sorted(seen):
            f.write(w + "\n")

    return out_file
