"""
Phase 2: Candidate word sourcing pipeline.
Downloads from Wiktionary, Hunspell, OpenThesaurus, Wikipedia, Gutenberg, SUBTLEX-DE;
normalizes and filters; deduplicates and tags provenance.
Output: data/candidates.txt, data/candidates_meta.jsonl.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sourcing.deduplicate import run as deduplicate_run
from sourcing.downloaders import hunspell
from sourcing.downloaders import openthesaurus
from sourcing.downloaders import wiktionary
from sourcing.downloaders import wikipedia
from sourcing.downloaders import gutenberg
from sourcing.downloaders import subtlex
from sourcing.downloaders import ne_contracted
from sourcing.downloaders import kaikki_forms
from sourcing.downloaders import wortschatz


SOURCES = [
    ("wiktionary", wiktionary),
    ("hunspell", hunspell),
    ("openthesaurus", openthesaurus),
    ("wikipedia", wikipedia),
    ("gutenberg", gutenberg),
    ("subtlex", subtlex),
    ("kaikki_forms", kaikki_forms),
    ("wortschatz", wortschatz),
    # ne_contracted must come last — it reads from all other sources' raw files
    ("ne_contracted", ne_contracted),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Source and merge German word candidates.")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "raw",
        help="Directory for raw downloads (sourcing/raw)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "data",
        help="Output directory for candidates (data/)",
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        default=[s[0] for s in SOURCES],
        help="Sources to run (default: all)",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download step; only run deduplication on existing raw data",
    )
    args = parser.parse_args()

    raw_dir = args.raw_dir
    data_dir = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        for name, mod in SOURCES:
            if name not in args.sources:
                continue
            try:
                source_dir = raw_dir / name
                print(f"Downloading {name}...")
                mod.download(source_dir)
                print(f"  -> {source_dir}")
            except Exception as e:
                print(f"  Warning: {name} failed: {e}")

    print("Deduplicating and writing candidates...")
    stats = deduplicate_run(
        raw_dir=raw_dir,
        out_candidates=data_dir / "candidates.txt",
        out_meta=data_dir / "candidates_meta.jsonl",
        source_names=args.sources,
    )
    print(f"Candidate count: {stats['candidate_count']}")
    print(f"Sources used: {stats['sources_used']}")
    print(f"Output: {data_dir / 'candidates.txt'}, {data_dir / 'candidates_meta.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
