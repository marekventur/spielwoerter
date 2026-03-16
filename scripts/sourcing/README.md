# Phase 2: Candidate Word Sourcing

Assembles German word candidates from freely-licensed sources, then normalizes, deduplicates, and tags provenance.

## Usage

From the project root:

```bash
# Install dependency
pip install -r requirements.txt

# Run full pipeline (download all sources, then deduplicate)
python -m sourcing.pipeline

# Download only specific sources
python -m sourcing.pipeline --sources hunspell wiktionary

# Skip download; only merge existing raw data into candidates
python -m sourcing.pipeline --skip-download

# Custom paths
python -m sourcing.pipeline --raw-dir sourcing/raw --data-dir data
```

## Sources

| Source        | Downloader              | Output in `sourcing/raw/{source}/` |
|---------------|-------------------------|------------------------------------|
| Wiktionary DE| Kaikki Wiktextract JSONL| `headwords.txt`                    |
| Hunspell de_DE| LanguageTool mirror     | `words.txt`                        |
| OpenThesaurus | REST API (suggest)      | `terms.txt`                        |
| Wikipedia DE  | Pagetitles dump (NS0)   | `titles.txt`                       |
| Gutenberg DE  | Gutendex + plain text   | `words.txt`                        |
| SUBTLEX-DE    | OSF (if available)       | `words.txt`                        |

Raw downloads are written under `sourcing/raw/{source_name}/`. The deduplication step merges all `words.txt` / `terms.txt` / `headwords.txt` files and writes:

- **data/candidates.txt** — one word per line, sorted, deduplicated
- **data/candidates_meta.jsonl** — one JSON object per line: `word`, `sources`, `source_count`, `count`

## Rate limiting (polite defaults)

- **OpenThesaurus**: 28 requests (empty + a–z + äöüß) with 0.5 s between calls. Set `FETCH_OPENTHESAURUS_FULL=1` to also query two-letter combos (800+ requests, ~0.3 s apart).
- **Gutenberg**: 1 Gutendex request + 25 book fetches with 1 s delay between each book.
- **Wiktionary / Wikipedia / Hunspell / SUBTLEX**: One (streaming) download each; no request burst.

## Normalization (sourcing/normalize.py)

- Lowercase, NFC Unicode normalization
- Strip accents that are not German umlauts (ä, ö, ü, ß)
- Filter: only `a-z`, ä, ö, ü, ß; length 2–15 (Scrabble constraint)

Downloaders apply these rules when producing word lists; deduplication expects already-normalized one-word-per-line files.
