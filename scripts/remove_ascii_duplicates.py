#!/usr/bin/env python3
"""
Removes ASCII spellings (ss for ß, ae/oe/ue for umlauts) that the moderators
struck on spielwoerter.de/pruefliste/ss, e.g. "abgiessen" next to "abgießen".

Input: scripts/data/ss_entscheidungen.tsv, the page's export
(ASCII form, decision, spelling with ß/umlaut, group). Only "streichen" rows
are applied, and only while the ß/umlaut spelling is still accepted, so a word
never disappears in both spellings. Struck forms move to the rejected list
with a description that names the valid spelling; "behalten" rows are left as
they are.

    python3 scripts/remove_ascii_duplicates.py            # rewrite the lists
    python3 scripts/remove_ascii_duplicates.py --dry-run  # report only
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPTED = ROOT / "wordlist_accepted.jsonl"
REJECTED = ROOT / "wordlist_rejected.jsonl"
DECISIONS = ROOT / "scripts/data/ss_entscheidungen.tsv"

REASONS = {
    "schweiz": "Schweizer Schreibweise von {b}; in der Liste gilt die Schreibung mit ß",
    "diphthong": "falsche Schreibung von {b} (ß nach Doppellaut)",
    "lang": "falsche Schreibung von {b} (ß nach langem Vokal)",
    "umlaut": "Ersatzschreibweise von {b}; Wörter werden mit Umlaut aufgenommen",
}


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", help="print the removed pairs as a markdown table")
    a = ap.parse_args()

    accepted, rejected = load(ACCEPTED), load(REJECTED)
    acc = {r["word"]: r for r in accepted}
    rej = {r["word"] for r in rejected}

    remove, skipped = [], []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        word, decision, sibling, group = line.split("\t")
        if decision != "streichen":
            continue
        if word not in acc:
            skipped.append((word, "nicht (mehr) in der Liste"))
        elif sibling not in acc:
            skipped.append((word, f"{sibling} ist nicht in der Liste"))
        else:
            remove.append((word, sibling, group))

    print(f"remove: {len(remove)}  skipped: {len(skipped)}")
    for w, why in skipped:
        print(f"  skipped {w}: {why}")
    if a.list:
        print("\n| entfernt | gültige Schreibung |\n|---|---|")
        for w, b, _ in remove:
            print(f"| {w} | {b} |")
    if a.dry_run:
        return

    gone = {w for w, _, _ in remove}
    accepted = [r for r in accepted if r["word"] not in gone]
    for word, sibling, group in remove:
        if word in rej:
            continue
        row = dict(acc[word])
        row["description"] = REASONS.get(group, "Ersatzschreibweise von {b}").format(b=sibling)
        row["source"], row["verified_by"] = "community", "moderator"
        insert_sorted(rejected, row)
    dump(ACCEPTED, accepted)
    dump(REJECTED, rejected)
    print(f"accepted: {len(acc)} -> {len(accepted)}; rejected: {len(rej)} -> {len(rejected)}")


if __name__ == "__main__":
    main()
