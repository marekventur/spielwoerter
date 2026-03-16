"""
Tokenize, normalize, and filter German word candidates.
- Lowercase, NFC unicode normalization.
- Only A–Z, Ä, Ö, Ü, ß; length 2–15 (Scrabble constraint).
- Strip accents that are not German umlauts (e.g. é → e for loanwords).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterator

# German Scrabble alphabet
ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzäöüß")
# Regex for tokenizing running text (letters + umlauts + ß)
WORD_PATTERN = re.compile(r"[a-zA-ZäöüÄÖÜß]+")


def _nfc_lower(s: str) -> str:
    return unicodedata.normalize("NFC", s.lower())


def _strip_non_umlaut_accents(s: str) -> str:
    """Replace accented letters with base letter except ä, ö, ü, ß."""
    result = []
    for c in s:
        if c in "äöüß":
            result.append(c)
            continue
        if c in ALLOWED_CHARS:
            result.append(c)
            continue
        decomposed = unicodedata.normalize("NFD", c)
        if len(decomposed) == 2 and decomposed[1] in "\u0300\u0301\u0302\u0303\u0308\u0327":
            base = decomposed[0]
            if base.isalpha() and base.lower() in "abcdefghijklmnopqrstuvwxyz":
                result.append(base.lower())
                continue
        result.append(c)
    return "".join(result)


def normalize_word(word: str) -> str | None:
    """
    Normalize a single word: NFC, lowercase, strip non-umlaut accents.
    Returns None if the word does not pass filters (allowed chars, length 2–15).
    """
    if not word or not word.strip():
        return None
    w = _nfc_lower(word.strip())
    w = _strip_non_umlaut_accents(w)
    if not all(c in ALLOWED_CHARS for c in w):
        return None
    if len(w) < 2 or len(w) > 15:
        return None
    return w


def tokenize_text(text: str) -> list[str]:
    """Extract word tokens from running text (letters + umlauts + ß)."""
    return WORD_PATTERN.findall(text)


def process_word_file(path: Path) -> Iterator[str]:
    """
    Read a file with one word per line; yield normalized words (no duplicates per file).
    """
    seen = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            w = normalize_word(line)
            if w and w not in seen:
                seen.add(w)
                yield w


def process_text_file(path: Path) -> Iterator[str]:
    """
    Read a raw text file; tokenize and yield normalized words (no duplicates per file).
    """
    seen = set()
    text = path.read_text(encoding="utf-8")
    for raw in tokenize_text(text):
        w = normalize_word(raw)
        if w and w not in seen:
            seen.add(w)
            yield w
