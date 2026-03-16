"""
Download German Wikipedia article text and extract word tokens.

Fetches random article extracts from the German Wikipedia API in batches,
tokenizes the plain text, and collects all unique German word forms.
This captures inflected forms as they actually appear in running prose,
unlike the previous approach that only used page titles (single words).

No huge dump download required — uses the MediaWiki API.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import requests

API_URL = "https://de.wikipedia.org/w/api.php"
BATCH_SIZE = 20       # articles per API request
NUM_BATCHES = 150     # 150 × 20 = 3 000 articles
DELAY = 0.5           # seconds between requests (be a good API citizen)

WORD_RE = re.compile(r"[a-zA-ZäöüÄÖÜß]+")
ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzäöüß")


def _fetch_batch(session: requests.Session) -> list[str]:
    """Return plain-text extracts for a batch of random articles."""
    params = {
        "action": "query",
        "generator": "random",
        "grnnamespace": 0,
        "grnlimit": BATCH_SIZE,
        "prop": "extracts",
        "exlimit": BATCH_SIZE,
        "explaintext": 1,
        "exsectionformat": "plain",
        "format": "json",
        "formatversion": 2,
    }
    try:
        r = session.get(API_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        pages = data.get("query", {}).get("pages", [])
        return [p.get("extract", "") for p in pages if p.get("extract")]
    except Exception:
        return []


def _load_titles(raw_dir: Path) -> set[str]:
    """Load single-word page titles from the existing titles.txt (if present)."""
    titles_file = raw_dir / "titles.txt"
    if not titles_file.exists():
        return set()
    words: set[str] = set()
    with open(titles_file, encoding="utf-8") as f:
        for line in f:
            w = line.strip().lower()
            if w and 2 <= len(w) <= 15 and all(c in ALLOWED for c in w):
                words.add(w)
    return words


def download(raw_dir: Path) -> Path:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "words.txt"

    # Start with page titles (single-word article names — many are valid German words)
    all_words: set[str] = _load_titles(raw_dir)
    print(f"  Loaded {len(all_words)} words from existing titles.txt")

    # Add article text from API
    session = requests.Session()
    session.headers["User-Agent"] = "german-wordlist-pipeline/1.0 (research)"

    for batch_idx in range(NUM_BATCHES):
        if batch_idx > 0:
            time.sleep(DELAY)
        extracts = _fetch_batch(session)
        for text in extracts:
            for m in WORD_RE.finditer(text):
                w = m.group(0).lower()
                if 2 <= len(w) <= 15 and all(c in ALLOWED for c in w):
                    all_words.add(w)

        if (batch_idx + 1) % 25 == 0:
            print(f"  {batch_idx + 1}/{NUM_BATCHES} API batches done, {len(all_words)} unique words so far")

    words_sorted = sorted(all_words)
    out_file.write_text("\n".join(words_sorted) + "\n", encoding="utf-8")
    print(f"  -> {len(words_sorted)} words written to {out_file}")
    return out_file
