"""
One-off data fix (2026-10): add the inflected forms with 10 or more letters
that the original 2-9 letter pipeline left out.

The moderators decided that the list is not bound to Scrabble's 9-letter limit
(Wortopia plays words of up to 25 letters). The morphology expansion
(scripts/morphology/expand.py) stopped at 9 letters, so long forms of words that
are already accepted are missing: "baumhäusern", "hektischere", "anzugrillen".

For every accepted word that is a headword in the German Wiktionary extract
(kaikki.org/dewiktionary), this script takes the forms listed there and adds the
ones that

  - have 10 or more letters (shorter ones are out of scope here: they were never
    cut by the limit, so if they are missing that has another reason),
  - are in none of the three lists (a moderator's rejection stays),
  - are pure inflections: every tag is case, number, gender, degree, tense or a
    participle/Gerundiv tag. That drops the "forms" Wiktionary lists that are not
    inflections at all: variants and Swiss spellings, diminutives and feminine
    derivations, labels like "Höflichkeitsform", related words.
  - for comparatives and superlatives (REGELN.md: "Steigerung nur, wenn
    sinngemäß vergleichbar"): only of adjectives that already have an accepted
    comparative or superlative. The others need a decision first and are only
    counted in the report.
  - not the Gerundiv or declined participles from verb entries ("abzufischende",
    "entlaufener"): REGELN.md allows them only for transitive verbs (participles
    also for intransitive ones with "sein"), and Wiktionary lists them for
    intransitive verbs as well ("anzugehörende"). Declined forms of participles
    that have their own adjective entry ("fesselnde") are included.

Usage:
    python3 scripts/expand_long_forms.py            # rewrite wordlist_accepted.jsonl
    python3 scripts/expand_long_forms.py --dry-run  # only print the report
    python3 scripts/expand_long_forms.py --dry-run --list  # ... with every word
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPTED = ROOT / "wordlist_accepted.jsonl"
UNCERTAIN = ROOT / "wordlist_uncertain.jsonl"
REJECTED = ROOT / "wordlist_rejected.jsonl"
KAIKKI = ROOT / "scripts/sourcing/raw/wiktionary/raw-wiktextract-data.jsonl.gz"

MIN_LEN = 10
VERIFIED_BY = "wiktionary-de"
VALID_RE = re.compile(r"^[a-zäöüß]+$")
SKIP_TAGS = {"auxiliary", "romanization", "obsolete"}

CASE = {"nominative": "Nominativ", "genitive": "Genitiv", "dative": "Dativ", "accusative": "Akkusativ"}
NUMBER = {"singular": "Singular", "plural": "Plural"}
GENDER = {"masculine", "feminine", "neuter"}
DEGREE = {"comparative": "Komparativ", "superlative": "Superlativ"}
DECLENSION = {"positive", "strong", "weak", "mixed", "predicative"}
VERB = {
    "participle", "participle-2", "perfect", "present", "past", "gerundive", "active",
    "passive", "extended", "infinitive", "subjunctive-ii", "separable", "inseparable",
    "regular", "irregular", "transitive", "intransitive", "auxiliary verb", "verb",
}
INFLECTION = set(CASE) | set(NUMBER) | GENDER | set(DEGREE) | DECLENSION
ALLOWED = {"noun": INFLECTION, "adj": INFLECTION, "verb": INFLECTION | VERB}


def is_inflection(pos: str, tags: frozenset) -> bool:
    if pos not in ALLOWED or not tags or not tags <= ALLOWED[pos]:
        return False
    if pos == "noun" and not tags & set(CASE):
        return False  # a bare "feminine" is a derived noun (Bohrer → Bohrerin), not a case
    return True


def needs_transitivity(pos: str, tags: frozenset) -> bool:
    """Gerundiv or declined participle of a verb: only valid for some verbs."""
    return pos == "verb" and ("gerundive" in tags or not tags & (VERB - {"positive"}))


def load_kaikki(path: Path) -> dict[str, dict[str, set[tuple[str, frozenset]]]]:
    """headword -> form -> {(pos, tags)} for the German entries."""
    out: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for raw in fh:
            e = json.loads(raw)
            if e.get("lang_code") != "de":
                continue
            hw, pos = e.get("word", "").strip().lower(), e.get("pos", "")
            if not hw:
                continue
            for fe in e.get("forms", []):
                form = fe.get("form", "").rstrip("!").strip().lower()
                tags = frozenset(fe.get("tags", []))
                if form and not tags & SKIP_TAGS:
                    out[hw][form].add((pos, tags))
    return out


def label(pos: str, tags: frozenset) -> str:
    """German description fragment for one tag set."""
    cases = [CASE[t] for t in CASE if t in tags]
    number = next((NUMBER[t] for t in NUMBER if t in tags), "")
    degree = next((DEGREE[t] for t in DEGREE if t in tags), "")
    declined = bool(cases) or bool(tags & {"strong", "weak", "mixed"})
    if pos == "noun":
        return " ".join(x for x in ("/".join(cases), number) if x)
    if pos == "verb":
        if "gerundive" in tags:
            return "Gerundiv, dekliniert" if declined else "Gerundiv"
        if "infinitive" in tags:
            return "Infinitiv mit zu"
        if "present" in tags and "participle" in tags:
            return "Partizip I"
        if tags & {"participle-2", "perfect"}:
            return "Partizip II"
        if "past" in tags:
            return "Präteritum"
        if "subjunctive-ii" in tags:
            return "Konjunktiv II"
        if "present" in tags:
            return "Präsens"
        return f"Partizip, {degree}, dekliniert" if degree else "Partizip, dekliniert"
    # adj
    if degree:
        return f"{degree}, dekliniert" if declined else degree
    return "deklinierte Form"


def noun_label(sets: set[tuple[str, frozenset]]) -> str:
    """Cases grouped by number: "Nominativ/Genitiv/Akkusativ Plural, Dativ Singular"."""
    by_number: dict[str, set[str]] = defaultdict(set)
    for _, tags in sets:
        for n in NUMBER:
            if n in tags:
                by_number[n] |= {c for c in CASE if c in tags}
    parts = []
    for n in NUMBER:
        if n in by_number:
            cases = by_number[n]
            parts.append(NUMBER[n] if len(cases) == 4 else "/".join(CASE[c] for c in CASE if c in cases) + " " + NUMBER[n])
    return ", ".join(parts)


def describe(hits: dict[str, set[tuple[str, frozenset]]]) -> str:
    parts = []
    for hw, sets in hits.items():
        nouns = {s for s in sets if s[0] == "noun"}
        labels = ([noun_label(nouns)] if nouns else []) + [
            label(pos, tags) for pos, tags in sorted(sets - nouns, key=lambda s: (s[0], sorted(s[1])))
        ]
        labels = list(dict.fromkeys(labels))
        name = hw.capitalize() if nouns == sets else hw
        parts.append(f"{', '.join(labels)} von {name}")
    return "; ".join(parts)


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def dump(path: Path, rows: list[dict]) -> None:
    # Same shape as lib/sync.ts toJsonl(): one JSON.stringify() per line.
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", help="with --dry-run: print every word")
    args = ap.parse_args()

    accepted = load(ACCEPTED)
    acc = {r["word"]: r for r in accepted}
    # Only words that were not added by this script are expanded and count as
    # evidence: otherwise a re-run would cascade (an added "angegrillt" is itself
    # a Wiktionary headword) and the result would depend on how often it ran.
    sources = {w for w, r in acc.items() if r.get("verified_by") != VERIFIED_BY}
    blocked = {r["word"] for r in load(REJECTED)} | {r["word"] for r in load(UNCERTAIN)}
    kaikki = load_kaikki(KAIKKI)

    def has_degree(sets) -> bool:
        return any(tags & set(DEGREE) for _, tags in sets)

    # Adjectives (and adjectival participles) the list already compares.
    comparable = {
        hw for hw in sources if hw in kaikki
        and any(f in sources and has_degree(sets) for f, sets in kaikki[hw].items())
    }

    new: dict[str, dict[str, set]] = {}
    skipped_degree: dict[str, str] = {}
    skipped_verb: dict[str, str] = {}
    for hw in sorted(sources):
        for form, sets in kaikki.get(hw, {}).items():
            if len(form) < MIN_LEN or not VALID_RE.match(form) or form in acc or form in blocked:
                continue
            # Inflections keep the first two letters (or start with ge-); this drops
            # the few unrelated words Wiktionary files under a headword.
            if form[:2] != hw[:2] and not form.startswith("ge"):
                continue
            good = {(pos, tags) for pos, tags in sets if is_inflection(pos, tags)}
            if good and all(needs_transitivity(pos, tags) for pos, tags in good):
                skipped_verb.setdefault(form, hw)
                continue
            good = {(pos, tags) for pos, tags in good if not needs_transitivity(pos, tags)}
            if not good:
                continue
            if all(tags & set(DEGREE) for _, tags in good) and hw not in comparable:
                skipped_degree.setdefault(form, hw)
                continue
            good = {(pos, tags) for pos, tags in good if not (tags & set(DEGREE)) or hw in comparable}
            new.setdefault(form, {})[hw] = good
    for form in new:
        skipped_degree.pop(form, None)
        skipped_verb.pop(form, None)

    by_len: dict[int, int] = defaultdict(int)
    for w in new:
        by_len[len(w)] += 1
    print(f"new forms: {len(new)}")
    print(f"left out: {len(skipped_degree)} comparatives/superlatives of adjectives without an accepted one, "
          f"{len(skipped_verb)} Gerundiv/declined participles of verbs")
    print("by length: " + ", ".join(f"{n}: {c}" for n, c in sorted(by_len.items())))
    if args.dry_run:
        if args.list:
            for form, hits in sorted(new.items()):
                print(f"{form}\t{next(iter(hits))}\t{describe(hits)}")
            print("\n## left out (comparison not confirmed)")
            for form, hw in sorted(skipped_degree.items()):
                print(f"{form}\t{hw}")
            print("\n## left out (Gerundiv/declined participle, transitivity not confirmed)")
            for form, hw in sorted(skipped_verb.items()):
                print(f"{form}\t{hw}")
        return

    # Append and re-sort once: same order as insertSorted() in lib/sync.ts
    # (plain code-point order), without 50k list insertions.
    for form, hits in new.items():
        accepted.append({
            "word": form,
            "description": describe(hits),
            "base": next(iter(hits)),
            "source": "morphology",
            "verified_by": VERIFIED_BY,
        })
    accepted.sort(key=lambda r: r["word"])
    dump(ACCEPTED, accepted)
    print(f"accepted: {len(acc)} -> {len(accepted)}")


if __name__ == "__main__":
    main()
