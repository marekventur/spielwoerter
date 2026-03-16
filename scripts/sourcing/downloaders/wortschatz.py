"""
Download and extract German word forms from the Leipzig Wortschatz corpora.

Uses two complementary corpora:
  - deu-de_web_2021_1M  : 1M sentences from German web (broad vocabulary)
  - deu_news_2021_1M    : 1M sentences from German news (formal register)

Each corpus ships a *-words.txt frequency list (rank TAB word TAB freq).
We extract all entries that are valid German word forms (alphabetic + umlauts,
2–15 chars) regardless of frequency rank — rare words are fine for Scrabble.

The archives are ~200-300 MB each; they are cached in raw_dir after the first
download so subsequent pipeline runs are fast.
"""
from __future__ import annotations

import io
import re
import tarfile
import urllib.request
from pathlib import Path

CORPORA = [
    (
        "deu-de_web_2021_1M",
        "https://downloads.wortschatz-leipzig.de/corpora/deu-de_web_2021_1M.tar.gz",
    ),
    (
        "deu_news_2021_1M",
        "https://downloads.wortschatz-leipzig.de/corpora/deu_news_2021_1M.tar.gz",
    ),
]

VALID_WORD = re.compile(r"^[a-zA-ZäöüÄÖÜß]{2,15}$")
ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzäöüß")


def _extract_words(tar_path: Path) -> set[str]:
    """Extract all valid German word forms from a Leipzig words.txt inside the archive."""
    words: set[str] = set()
    with tarfile.open(tar_path, "r:gz") as tf:
        words_member = next(
            (m for m in tf.getmembers() if m.name.endswith("-words.txt")), None
        )
        if words_member is None:
            print(f"  Warning: no *-words.txt found in {tar_path.name}")
            return words
        f = tf.extractfile(words_member)
        if f is None:
            return words
        for line in f:
            parts = line.decode("utf-8", errors="replace").strip().split("\t")
            if len(parts) < 2:
                continue
            w = parts[1].lower()
            if VALID_WORD.match(w) and all(c in ALLOWED for c in w):
                words.add(w)
    return words


def download(raw_dir: Path) -> Path:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "words.txt"

    all_words: set[str] = set()

    for corpus_name, url in CORPORA:
        tar_path = raw_dir / f"{corpus_name}.tar.gz"
        if not tar_path.exists():
            print(f"  Downloading {corpus_name} (~200-300 MB)...")
            urllib.request.urlretrieve(url, tar_path)
            print(f"  Downloaded: {tar_path.stat().st_size / 1e6:.1f} MB")
        else:
            print(f"  Using cached {tar_path.name} ({tar_path.stat().st_size / 1e6:.1f} MB)")

        words = _extract_words(tar_path)
        print(f"  {corpus_name}: {len(words):,} valid German words")
        all_words |= words

    words_sorted = sorted(all_words)
    out_file.write_text("\n".join(words_sorted) + "\n", encoding="utf-8")
    print(f"  -> {len(words_sorted):,} total unique words written to {out_file}")
    return out_file
