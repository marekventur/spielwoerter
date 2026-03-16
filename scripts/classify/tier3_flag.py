"""
Tier 3: Flag low-confidence / UNCERTAIN words for human review.
Reads tier2_results.jsonl and candidates_meta.jsonl, writes tier3_review.txt with context.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_meta(meta_path: Path) -> dict[str, dict]:
    """word -> { sources, count, ... }"""
    meta = {}
    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                meta[rec["word"]] = rec
            except (json.JSONDecodeError, KeyError):
                continue
    return meta


def run(
    results_path: Path,
    meta_path: Path,
    out_path: Path,
    *,
    include_medium_confidence: bool = False,
) -> int:
    """
    Filter tier2_results where classification == UNCERTAIN or confidence == LOW
    (optionally also MEDIUM). Write review file with word, reason, sources, count.
    """
    results_path = Path(results_path)
    if not results_path.exists():
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("", encoding="utf-8")
        return 0

    meta = load_meta(Path(meta_path))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(results_path, "r", encoding="utf-8") as f_in, open(
        out_path, "w", encoding="utf-8"
    ) as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            classification = rec.get("classification", "")
            confidence = rec.get("confidence", "")
            if classification != "UNCERTAIN" and confidence != "LOW":
                if not include_medium_confidence or confidence != "MEDIUM":
                    continue
            word = rec.get("word", "")
            reason = rec.get("reason", "")
            m = meta.get(word, {})
            sources = m.get("sources", [])
            source_count = m.get("source_count", 0)
            cnt = m.get("count", 0)
            # Tab-separated: word, reason, sources (comma-joined), source_count, count
            sources_str = ",".join(sources) if sources else ""
            f_out.write(f"{word}\t{reason}\t{sources_str}\t{source_count}\t{cnt}\n")
            count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Tier 3: flag UNCERTAIN/LOW for review.")
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("data/tier2_results.jsonl"),
        help="Path to tier2_results.jsonl",
    )
    parser.add_argument(
        "--meta",
        type=Path,
        default=Path("data/candidates_meta.jsonl"),
        help="Path to candidates_meta.jsonl (for provenance)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/tier3_review.txt"),
        help="Output path for tier3_review.txt",
    )
    parser.add_argument(
        "--include-medium",
        action="store_true",
        help="Also include MEDIUM confidence words in review set",
    )
    args = parser.parse_args()

    n = run(args.results, args.meta, args.out, include_medium_confidence=args.include_medium)
    print(f"Flagged {n} words for review -> {args.out}")


if __name__ == "__main__":
    main()
