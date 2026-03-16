"""
Phase 4: Morphological Expansion
=================================
Takes a classified word list (TSV from tier2_llm.py) and expands each accepted
word to all its inflected forms using the Kaikki Wiktionary JSONL.

For each accepted word:
  1. Use the `base` field from TSV if available (lemma provided by LLM)
  2. Try the word itself as a Kaikki headword
  3. Try a reverse lookup: word-as-form → Kaikki headword(s)
Then emit all Kaikki forms for the resolved headword(s).

Output: expanded word list + stats.

Usage:
    python3 -m morphology.expand \\
        --tsv data/calibration_frac10_gosd_10pct_deepseek_t0p3_double_results.tsv \\
        --candidates data/candidates.txt \\
        --output data/morphology_expanded.txt \\
        [--corpus-only]          # only emit forms attested in candidates.txt
        [--kaikki scripts/sourcing/raw/wiktionary/raw-wiktextract-data.jsonl.gz]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import tqdm

KAIKKI_DEFAULT = Path("scripts/sourcing/raw/wiktionary/raw-wiktextract-data.jsonl.gz")
VALID_RE = re.compile(r"^[a-zäöüß]+$")
MIN_LEN, MAX_LEN = 2, 9

# Tags that indicate the form entry is metadata, not an actual word form
SKIP_TAGS = {"auxiliary", "romanization", "obsolete"}

# Form strings that are obviously not word forms (auxiliaries listed as forms in verb tables)
AUXILIARY_WORDS = {"haben", "sein", "werden"}


def is_valid_form(s: str) -> bool:
    return MIN_LEN <= len(s) <= MAX_LEN and bool(VALID_RE.match(s))


def clean_form(s: str) -> str:
    """Strip punctuation artifacts like imperative '!'."""
    return s.rstrip("!").strip()


def load_kaikki(path: Path) -> tuple[dict, dict]:
    """
    Returns:
        headword_to_forms: {lowercase_headword: {lowercase_form, ...}}
        form_to_headwords: {lowercase_form: {lowercase_headword, ...}}
    """
    headword_to_forms: dict[str, set[str]] = defaultdict(set)
    form_to_headwords: dict[str, set[str]] = defaultdict(set)

    print(f"Loading Kaikki JSONL from {path}…", file=sys.stderr)
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path) as f:
        for raw in tqdm.tqdm(f, desc="Kaikki entries", unit="entry"):
            entry = json.loads(raw)
            if entry.get("lang_code") != "de":
                continue

            headword = entry.get("word", "")
            hw = clean_form(headword).lower()
            if not hw:
                continue

            # The headword itself is a valid form
            headword_to_forms[hw].add(hw)
            if is_valid_form(hw):
                form_to_headwords[hw].add(hw)

            for form_entry in entry.get("forms", []):
                raw_form = form_entry.get("form", "")
                form = clean_form(raw_form).lower()
                if not form:
                    continue

                tags = set(form_entry.get("tags", []))
                # Skip metadata/auxiliary entries
                if tags & SKIP_TAGS:
                    continue
                if form in AUXILIARY_WORDS and "auxiliary" not in tags:
                    # listed as a form string but is an auxiliary verb — skip
                    if form != hw:
                        continue

                headword_to_forms[hw].add(form)
                if is_valid_form(form):
                    form_to_headwords[form].add(hw)

    print(
        f"  Headwords: {len(headword_to_forms):,}  |  Indexed forms: {len(form_to_headwords):,}",
        file=sys.stderr,
    )
    return dict(headword_to_forms), dict(form_to_headwords)


def load_tsv(path: Path) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def resolve_headwords(
    word: str,
    base: str,
    headword_to_forms: dict,
    form_to_headwords: dict,
) -> set[str]:
    """Return the set of Kaikki headwords for this accepted word."""
    candidates = set()

    # 1. LLM-provided base form
    if base and base in headword_to_forms:
        candidates.add(base)

    # 2. Word itself is a headword
    if word in headword_to_forms:
        candidates.add(word)

    # 3. Reverse lookup: word appears as a form of some headword
    if word in form_to_headwords:
        candidates |= form_to_headwords[word]

    return candidates


def expand(
    tsv_path: Path,
    kaikki_path: Path,
    candidates_path: Path | None,
    output_path: Path,
    corpus_only: bool,
) -> None:
    headword_to_forms, form_to_headwords = load_kaikki(kaikki_path)

    print("Loading TSV results…", file=sys.stderr)
    rows = load_tsv(tsv_path)
    accepted = [r for r in rows if r.get("valid") == "ja"]
    print(f"  Accepted words in TSV: {len(accepted):,}", file=sys.stderr)

    corpus: set[str] | None = None
    if candidates_path:
        print("Loading candidates (corpus attestation check)…", file=sys.stderr)
        with open(candidates_path) as f:
            corpus = {line.strip() for line in f if line.strip()}
        print(f"  Corpus size: {len(corpus):,}", file=sys.stderr)

    # Expand
    already_accepted = {r["word"] for r in accepted}
    expanded_forms: set[str] = set()
    headwords_used: set[str] = set()
    no_kaikki_match = 0

    for row in tqdm.tqdm(accepted, desc="Expanding", unit="word"):
        word = row["word"]
        base = (row.get("base") or "").strip().lower()

        headwords = resolve_headwords(word, base, headword_to_forms, form_to_headwords)
        if not headwords:
            no_kaikki_match += 1
            continue

        headwords_used |= headwords
        for hw in headwords:
            for form in headword_to_forms.get(hw, set()):
                if not is_valid_form(form):
                    continue
                if corpus_only and corpus and form not in corpus:
                    continue
                expanded_forms.add(form)

    new_forms = expanded_forms - already_accepted
    print(f"\n=== Morphological Expansion Results ===", file=sys.stderr)
    print(f"  Accepted words:              {len(already_accepted):,}", file=sys.stderr)
    print(f"  Words with no Kaikki match:  {no_kaikki_match:,}  ({no_kaikki_match/len(accepted)*100:.1f}%)", file=sys.stderr)
    print(f"  Unique headwords resolved:   {len(headwords_used):,}", file=sys.stderr)
    print(f"  Total expanded forms:        {len(expanded_forms):,}", file=sys.stderr)
    print(f"  NEW forms (not in accepted): {len(new_forms):,}", file=sys.stderr)
    if corpus:
        corpus_attested = expanded_forms & corpus
        print(f"  Corpus-attested forms:       {len(corpus_attested):,}", file=sys.stderr)
        new_corpus_attested = new_forms & corpus
        print(f"  NEW corpus-attested forms:   {len(new_corpus_attested):,}", file=sys.stderr)

    # Combined output: accepted + new expanded forms
    combined = already_accepted | new_forms
    print(f"\n  Combined list size:          {len(combined):,}", file=sys.stderr)
    print(f"  Growth factor:               +{len(new_forms)/len(already_accepted)*100:.1f}%", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for w in sorted(combined):
            f.write(w + "\n")
    print(f"\nWritten to {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Phase 4: Morphological expansion")
    parser.add_argument("--tsv", required=True, help="Tier2 results TSV")
    parser.add_argument("--kaikki", default=str(KAIKKI_DEFAULT), help="Kaikki JSONL(.gz)")
    parser.add_argument("--candidates", default="data/candidates.txt", help="Candidates file for corpus attestation")
    parser.add_argument("--output", default="data/morphology_expanded.txt")
    parser.add_argument("--corpus-only", action="store_true",
                        help="Only include generated forms that appear in candidates.txt")
    args = parser.parse_args()

    expand(
        tsv_path=Path(args.tsv),
        kaikki_path=Path(args.kaikki),
        candidates_path=Path(args.candidates) if args.candidates else None,
        output_path=Path(args.output),
        corpus_only=args.corpus_only,
    )


if __name__ == "__main__":
    main()
