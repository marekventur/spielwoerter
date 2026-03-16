"""
Download OpenThesaurus.de term list via their REST API.
Uses suggest endpoint only; rate-limited to avoid hammering the service.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

BASE = "https://www.openthesaurus.de"
SUGGEST_URL = f"{BASE}/synonyme/suggest"

# Rate limit: seconds between API calls (default run = 28 calls total)
DELAY_BETWEEN_REQUESTS = 0.5
# If FETCH_OPENTHESAURUS_FULL=1, also query two-letter combos (800+ calls, ~7+ min)
DELAY_FULL_BETWEEN_REQUESTS = 0.3


def _fetch_suggest(q: str) -> list[str]:
    r = requests.get(SUGGEST_URL, params={"q": q}, timeout=30)
    r.raise_for_status()
    data = r.json()
    terms = []
    for cat in ("terms", "superterms", "subterms", "similar", "substring"):
        for item in data.get(cat, []):
            t = item.get("term")
            if isinstance(t, str) and t.strip():
                terms.append(t.strip())
    return terms


def download(raw_dir: Path) -> Path:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "terms.txt"

    # Single letters + empty (28 requests total)
    queries = [""] + [c for c in "abcdefghijklmnopqrstuvwxyzäöüß"]
    all_terms = set()
    for i, q in enumerate(queries):
        try:
            terms = _fetch_suggest(q)
            all_terms.update(terms)
        except Exception:
            pass
        if i < len(queries) - 1:
            time.sleep(DELAY_BETWEEN_REQUESTS)

    # Optional: two-letter combos only if explicitly requested (800+ requests)
    if os.environ.get("FETCH_OPENTHESAURUS_FULL"):
        delay = DELAY_FULL_BETWEEN_REQUESTS
        for a in "abcdefghijklmnopqrstuvwxyz":
            for b in "abcdefghijklmnopqrstuvwxyzäöü":
                if len(all_terms) > 150_000:
                    break
                try:
                    terms = _fetch_suggest(a + b)
                    all_terms.update(terms)
                except Exception:
                    pass
                time.sleep(delay)
            if len(all_terms) > 150_000:
                break

    allowed = set("abcdefghijklmnopqrstuvwxyzäöüß")
    lines = sorted(
        w.lower()
        for w in all_terms
        if w
        and len(w) >= 2
        and len(w) <= 15
        and all(c in allowed for c in w.lower())
    )
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_file
