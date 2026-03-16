"""
Generate stats.json from the accepted and uncertain wordlists, including oracle metrics.

Usage:
    python3 -m scripts.generate_stats [--skip-oracle]

The oracle requires a network connection on first run to download deutsch.dic (~10 MB).
Pass --skip-oracle to generate stats without oracle metrics.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ACCEPTED_PATH = Path("wordlist_accepted.jsonl")
UNCERTAIN_PATH = Path("wordlist_uncertain.jsonl")
ORACLE_PATH = Path("scripts/oracle/wordlist_oracle.py")
OUT_PATH = Path("stats.json")


def run_oracle(words: list[str]) -> dict | None:
    """Pipe words (uppercase) through the oracle and return parsed JSON output."""
    print("Running oracle...", file=sys.stderr)
    try:
        result = subprocess.run(
            [sys.executable, str(ORACLE_PATH), "--language", "deutsch"],
            input="\n".join(words),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Oracle failed: {e.stderr}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Oracle error: {e}", file=sys.stderr)
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-oracle", action="store_true", help="Skip oracle metrics")
    args = parser.parse_args()

    accepted = [json.loads(line) for line in ACCEPTED_PATH.read_text().splitlines() if line.strip()]
    uncertain = [json.loads(line) for line in UNCERTAIN_PATH.read_text().splitlines() if line.strip()]

    by_source = Counter(w["source"] for w in accepted)
    by_pass = Counter(w["classification_pass"] for w in accepted if w.get("classification_pass"))
    length_dist = Counter(len(w["word"]) for w in accepted)

    stats = {
        "generated": str(date.today()),
        "accepted": {
            "total": len(accepted),
            "by_source": dict(sorted(by_source.items())),
            "by_classification_pass": dict(sorted(by_pass.items())),
            "length_distribution": {str(k): v for k, v in sorted(length_dist.items())},
        },
        "uncertain": {
            "total": len(uncertain),
        },
    }

    if not args.skip_oracle:
        words = [w["word"].upper() for w in accepted]
        oracle = run_oracle(words)
        if oracle:
            stats["oracle"] = {
                "reference_total": oracle["reference_total"],
                "precision_pct": oracle["precision_pct"],
                "recall_pct": oracle["recall_pct"],
                "true_positives": oracle["true_positives"],
                "false_positives": oracle["false_positives"],
                "false_negatives": oracle["false_negatives"],
            }
            print(f"  Oracle: precision={oracle['precision_pct']}%  recall={oracle['recall_pct']}%")
        else:
            print("  Oracle: skipped (failed)", file=sys.stderr)

    OUT_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")
    print(f"Written {OUT_PATH}")
    print(f"  Total accepted: {len(accepted):,}")
    for src, n in sorted(by_source.items()):
        print(f"    {src}: {n:,}")
    print(f"  Uncertain: {len(uncertain):,}")


if __name__ == "__main__":
    main()
