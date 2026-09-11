"""
One-off data fix (2026-09): drop invalid 2nd-person forms of verbs on -eln/-ern.

The Kaikki/Wiktionary conjugation tables that fed the morphology expansion
(and the LLM pass that approved many of the same candidates) list forms such
as "büglest", "büglet", "feirest", "feiret" and "feierest", "feieret". Under
REGELN.md the contracted stem (bügl-, feir-) is only allowed in the 1st person
singular and the imperative singular, and verbs on -eln/-ern do not take -est/-et
in the 2nd person. Reported by moderator Panikpilz on the moderator board.

For every accepted verb lemma ending in -eln/-ern (description starts with
"Verb") the script looks for these four shapes in the accepted list and moves
them to the rejected list, with the lemma as `base` and a German description
saying why. The contracted -st/-t shapes (büglst, feirst) are deliberately
not touched: the few hits are valid forms of other verbs (nährst from nähren,
knäulst from knäulen).

Usage:
    python3 scripts/remove_eln_ern_konjunktiv.py            # rewrite the lists
    python3 scripts/remove_eln_ern_konjunktiv.py --dry-run  # only print the list
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPTED = ROOT / "wordlist_accepted.jsonl"
REJECTED = ROOT / "wordlist_rejected.jsonl"

CONTRACTED = (
    "Ungültige Beugungsform von {lemma}: die verkürzte Stammform (e-Tilgung) "
    "ist nur in der 1. Person Singular und im Imperativ Singular zulässig."
)
FULL_STEM = (
    "Ungültige Beugungsform von {lemma}: Verben auf -eln/-ern bilden die "
    "2. Person nicht mit -est/-et."
)


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def dump(path: Path, rows: list[dict]) -> None:
    # Same shape as lib/sync.ts toJsonl(): one JSON.stringify() per line.
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def insert_sorted(rows: list[dict], entry: dict) -> None:
    # Mirrors insertSorted() in lib/sync.ts: before the first word that sorts after it.
    for i, r in enumerate(rows):
        if r["word"] > entry["word"]:
            rows.insert(i, entry)
            return
    rows.append(entry)


def candidates(lemma: str) -> dict[str, str]:
    stem = lemma[:-1]                 # bügel / feier
    contracted = stem[:-2] + stem[-1]  # bügl / feir
    return {
        contracted + "est": "contracted",
        contracted + "et": "contracted",
        stem + "est": "full",
        stem + "et": "full",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    accepted = load(ACCEPTED)
    rejected = load(REJECTED)
    by_word = {r["word"]: r for r in accepted}

    lemmas = sorted(
        w
        for w, r in by_word.items()
        if (r.get("description") or "").startswith("Verb")
        and (w.endswith("eln") or w.endswith("ern"))
        and len(w) > 4
    )

    moves: dict[str, tuple[str, str]] = {}  # form -> (lemma, kind)
    for lemma in lemmas:
        for form, kind in candidates(lemma).items():
            if form in by_word and form not in moves:
                moves[form] = (lemma, kind)

    groups = {"contracted": [], "full": []}
    for form, (lemma, kind) in sorted(moves.items()):
        groups[kind].append(f"{form} ({lemma})")
    print(f"contracted stem + est/et: {len(groups['contracted'])}")
    print(f"full stem + est/et:       {len(groups['full'])}")
    print(f"total:                    {len(moves)}")
    if args.dry_run:
        for kind, items in groups.items():
            print(f"\n## {kind}\n" + "\n".join(items))
        return

    kept = [r for r in accepted if r["word"] not in moves]
    for form, (lemma, kind) in sorted(moves.items()):
        row = dict(by_word[form])
        row["description"] = (CONTRACTED if kind == "contracted" else FULL_STEM).format(lemma=lemma)
        row["base"] = lemma
        rejected = [r for r in rejected if r["word"] != form]
        insert_sorted(rejected, row)

    dump(ACCEPTED, kept)
    dump(REJECTED, rejected)
    print(f"accepted: {len(accepted)} -> {len(kept)}; rejected: -> {len(rejected)}")


if __name__ == "__main__":
    main()
