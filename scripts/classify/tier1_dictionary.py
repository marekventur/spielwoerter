"""
Tier 1: Multi-source dictionary match.
Words in 2+ curated dictionary sources (Wiktionary, OpenThesaurus, hunspell) are auto-accepted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tqdm import tqdm

DICTIONARY_SOURCES = frozenset({"wiktionary", "openthesaurus", "hunspell"})


def run(
    candidates_meta: Path,
    data_dir: Path,
) -> dict[str, int]:
    """
    Stream candidates_meta.jsonl; for each word, count dictionary sources.
    If dict_count >= 2 -> tier1_accepted.txt, else -> tier2_candidates.txt.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_tier1 = data_dir / "tier1_accepted.txt"
    out_tier2 = data_dir / "tier2_candidates.txt"
    out_stats = data_dir / "tier1_stats.json"

    tier1_count = 0
    tier2_count = 0

    with open(candidates_meta, "r", encoding="utf-8") as f_in, open(
        out_tier1, "w", encoding="utf-8"
    ) as f1, open(out_tier2, "w", encoding="utf-8") as f2:
        for line in tqdm(f_in, desc="Tier 1"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            word = rec.get("word", "")
            sources = rec.get("sources", [])
            dict_count = len([s for s in sources if s in DICTIONARY_SOURCES])
            if dict_count >= 2:
                f1.write(word + "\n")
                tier1_count += 1
            else:
                f2.write(word + "\n")
                tier2_count += 1

    stats = {"tier1_count": tier1_count, "tier2_count": tier2_count}
    with open(out_stats, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Tier 1: split candidates by dictionary source count.")
    parser.add_argument(
        "--candidates-meta",
        type=Path,
        default=Path("data/candidates_meta.jsonl"),
        help="Path to candidates_meta.jsonl",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Output directory for tier1_accepted.txt, tier2_candidates.txt, tier1_stats.json",
    )
    args = parser.parse_args()

    stats = run(args.candidates_meta, args.data_dir)
    print(f"Tier 1 accepted: {stats['tier1_count']}")
    print(f"Tier 2 candidates: {stats['tier2_count']}")


if __name__ == "__main__":
    main()
