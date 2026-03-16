"""
Generate contracted (syncopated) participial adjective forms.

In German, adjectives derived from past participles can drop the medial -e-
when the inflectional ending begins with a consonant cluster. These are valid
Scrabble words present in the reference dictionary (Gero Illing / Duden RD-29).

Examples:
  gestohlene  → gestohlne   (nom/acc sg f)
  gestohlenem → gestohlenem  (wait — correct: gestohlenem stays)
  gestohlener → gestohlenEr  (strong m/n gen — but contracted: gestohLNer)

More precisely, the contraction rule is:
  word ending in [consonant] + ene  → drop the first e → [consonant] + ne
  word ending in [consonant] + ener → [consonant] + ner
  word ending in [consonant] + enem → [consonant] + nem
  word ending in [consonant] + enen → [consonant] + nen
  word ending in [consonant] + enes → [consonant] + nes

This generator reads all existing raw word sources and applies the rule,
writing unique contracted forms to its own words.txt.
"""
from __future__ import annotations

import re
from pathlib import Path

# Endings to contract and their replacements (full suffix → contracted suffix)
CONTRACTIONS = [
    ("ene",  "ne"),
    ("ener", "ner"),
    ("enem", "nem"),
    ("enen", "nen"),
    ("enes", "nes"),
]

VOWELS = frozenset("aeiouäöü")
VALID_WORD = re.compile(r"^[a-zA-ZäöüÄÖÜß]{2,15}$")


def _contract_word(word: str) -> str | None:
    """Return the contracted form of word if applicable, else None."""
    for sfx, contracted_sfx in CONTRACTIONS:
        if not word.endswith(sfx):
            continue
        if len(word) <= len(sfx):
            continue
        char_before = word[-(len(sfx) + 1)]
        if char_before in VOWELS:
            continue  # e.g. "Biene" — vowel before ene, not a participial contraction
        contracted = word[: -len(sfx)] + contracted_sfx
        if VALID_WORD.match(contracted):
            return contracted
    return None


def _iter_source_words(raw_dir: Path):
    """Yield all lowercased words from all sibling source word files."""
    for words_file in raw_dir.parent.glob("*/words.txt"):
        with open(words_file, encoding="utf-8") as f:
            for line in f:
                w = line.strip().lower()
                if w:
                    yield w
    # Also include wiktionary headwords (named differently)
    hw = raw_dir.parent / "wiktionary" / "headwords.txt"
    if hw.exists():
        with open(hw, encoding="utf-8") as f:
            for line in f:
                w = line.strip().lower()
                if w:
                    yield w


def download(raw_dir: Path) -> Path:
    """
    'download' is a misnomer here — this step generates forms from existing sources.
    No network access needed; it reads from sibling raw/* directories.
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "words.txt"

    contracted: set[str] = set()
    seen_inputs: set[str] = set()

    for word in _iter_source_words(raw_dir):
        if word in seen_inputs:
            continue
        seen_inputs.add(word)
        form = _contract_word(word)
        if form:
            contracted.add(form.lower())

    words_sorted = sorted(contracted)
    out_file.write_text("\n".join(words_sorted) + "\n", encoding="utf-8")
    print(f"  -> {len(words_sorted)} contracted NE-forms written to {out_file}")
    return out_file
