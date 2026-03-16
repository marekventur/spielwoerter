"""
Download a sample of German Project Gutenberg texts and extract word tokens.
Uses the PG API to list German-language books and fetches plain text.
Rate-limited to avoid hammering gutenberg.org.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import requests

# Project Gutenberg API (third-party, no strict limit)
PG_API = "https://gutendex.com/books"
LANG = "de"
# Keep request count reasonable: 1 list + N book fetches
MAX_BOOKS = 25
# Seconds between each book download (gutenberg.org is volunteer-run)
DELAY_BETWEEN_BOOKS = 1.0


def download(raw_dir: Path) -> Path:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "words.txt"

    r = requests.get(PG_API, params={"languages": LANG}, timeout=30)
    r.raise_for_status()
    data = r.json()
    results = data.get("results", [])[:MAX_BOOKS]

    base_txt = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
    allowed = set("abcdefghijklmnopqrstuvwxyzäöüß")
    word_re = re.compile(r"[a-zA-ZäöüÄÖÜß]+")

    all_words = set()
    for i, book in enumerate(results):
        if i > 0:
            time.sleep(DELAY_BETWEEN_BOOKS)
        book_id = book.get("id")
        if not book_id:
            continue
        url = base_txt.format(id=book_id)
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code != 200:
                continue
            text = resp.text
        except Exception:
            continue
        for m in word_re.finditer(text):
            w = m.group(0).lower()
            if 2 <= len(w) <= 15 and all(c in allowed for c in w):
                all_words.add(w)

    with open(out_file, "w", encoding="utf-8") as f:
        for w in sorted(all_words):
            f.write(w + "\n")
    return out_file
