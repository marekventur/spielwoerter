"""
Deduplicate words across sources and tag provenance.
Consumes per-source word lists (and optional frequency data) and produces
data/candidates.txt plus data/candidates_meta.jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

def load_source_words(source_path: Path, min_len: int = 2, max_len: int = 15) -> set[str]:
    """Load normalized words from a one-word-per-line file (Scrabble length 2–15)."""
    allowed = set("abcdefghijklmnopqrstuvwxyzäöüß")
    words = set()
    with open(source_path, "r", encoding="utf-8") as f:
        for line in f:
            w = line.strip().lower()
            if w and min_len <= len(w) <= max_len and all(c in allowed for c in w):
                words.add(w)
    return words


def run(
    raw_dir: Path,
    out_candidates: Path,
    out_meta: Path,
    source_names: list[str] | None = None,
) -> dict[str, int]:
    """
    Merge all source word files under raw_dir, deduplicate, tag provenance.
    Each source should have a subdir raw_dir/{source_name}/ with words.txt (or terms.txt, etc.).
    Writes out_candidates (one word per line, sorted) and out_meta (JSONL: word, sources[], count).
    Returns stats: candidate_count, reference_count (0), etc.
    """
    raw_dir = Path(raw_dir)
    out_candidates = Path(out_candidates)
    out_meta = Path(out_meta)

    if source_names is None:
        source_names = [
            "wiktionary",
            "hunspell",
            "openthesaurus",
            "wikipedia",
            "gutenberg",
            "subtlex",
        ]

    # word -> { sources: [...], count: N }
    merged: dict[str, dict[str, Any]] = {}

    for name in source_names:
        d = raw_dir / name
        if not d.is_dir():
            continue
        # Prefer words.txt, else terms.txt, else any .txt
        candidates = [d / "words.txt", d / "terms.txt", d / "headwords.txt"]
        path = None
        for p in candidates:
            if p.exists():
                path = p
                break
        if path is None:
            for p in d.glob("*.txt"):
                path = p
                break
        if path is None:
            continue
        words = load_source_words(path)
        for w in words:
            if w not in merged:
                merged[w] = {"sources": [], "count": 0}
            merged[w]["sources"].append(name)
            merged[w]["count"] += 1

    # Remove ae/oe/ue transliterations when the proper umlaut form also exists.
    # E.g. remove "abhaengen" if "abhängen" is already in the set.
    # ss->ß is intentionally excluded: both spellings are valid in modern German.
    word_set = set(merged.keys())
    to_remove: set[str] = set()
    for w in word_set:
        if any(c in w for c in "äöüß"):
            continue  # already has proper chars
        for ascii_seq, umlaut_char in (("ae", "ä"), ("oe", "ö"), ("ue", "ü")):
            if ascii_seq not in w:
                continue
            idx = 0
            while True:
                pos = w.find(ascii_seq, idx)
                if pos == -1:
                    break
                candidate = w[:pos] + umlaut_char + w[pos + 2 :]
                if candidate in word_set:
                    to_remove.add(w)
                    break
                idx = pos + 1
            if w in to_remove:
                break

    for w in to_remove:
        del merged[w]

    # Sort words for stable output
    sorted_words = sorted(merged.keys())

    out_candidates.parent.mkdir(parents=True, exist_ok=True)
    with open(out_candidates, "w", encoding="utf-8") as f:
        for w in sorted_words:
            f.write(w + "\n")

    with open(out_meta, "w", encoding="utf-8") as m:
        for w in sorted_words:
            rec = merged[w]
            meta = {
                "word": w,
                "sources": list(dict.fromkeys(rec["sources"])),
                "source_count": len(dict.fromkeys(rec["sources"])),
                "count": rec["count"],
            }
            m.write(json.dumps(meta, ensure_ascii=False) + "\n")

    return {
        "candidate_count": len(merged),
        "sources_used": len([n for n in source_names if (raw_dir / n).is_dir()]),
    }
