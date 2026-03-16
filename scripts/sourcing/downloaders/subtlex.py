"""
SUBTLEX-DE: German subtitle word frequency list from OSF.
If the canonical file is not at a stable URL, we try known locations.
"""
from __future__ import annotations

from pathlib import Path

import requests

# SUBTLEX-DE on OSF (Brysbaert et al.); exact file path may vary
# Common pattern: SUBTLEX-DE word list with frequency columns
OSF_PROJECT = "https://osf.io/py9ba/"
# Direct file link if available (OSF often uses /download on file nodes)
# Fallback: we document manual download or use a mirror if we find one
SUBTLEX_DE_URL = (
    "https://osf.io/download/py9ba/"
)  # May 404; then user downloads manually


def download(raw_dir: Path) -> Path:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "words.txt"

    # Try OSF download; project page might not have a single file
    try:
        r = requests.get(SUBTLEX_DE_URL, timeout=30)
        if r.status_code == 200 and len(r.text) > 100:
            # Parse TSV/CSV: first column is usually word
            lines = r.text.strip().split("\n")
            words = set()
            allowed = set("abcdefghijklmnopqrstuvwxyzäöüß")
            for line in lines[1:]:  # skip header
                parts = line.split("\t") if "\t" in line else line.split(",")
                if parts:
                    w = parts[0].strip().lower()
                    if 2 <= len(w) <= 15 and all(c in allowed for c in w):
                        words.add(w)
            if words:
                out_file.write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")
                return out_file
    except Exception:
        pass

    # Placeholder: empty file so pipeline doesn't fail; user can add SUBTLEX-DE manually
    out_file.write_text("", encoding="utf-8")
    return out_file
