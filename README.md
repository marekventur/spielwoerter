# spielwoerter

**spielwoerter** ist die umfassendste, frei lizenzierte deutsche Wortliste für Wortspiele. Sie enthält über 200.000 Einträge — Substantive, Verben, Adjektive und alle gängigen Beugungsformen — und eignet sich für Scrabble, Wordle-Varianten und ähnliche Spiele.

Die Liste steht unter der **CC0-Lizenz** (Public Domain) und kann kostenlos und ohne Einschränkungen verwendet werden. Auf [spielwoerter.de](https://spielwoerter.de/) kann die Community einzelne Wörter überprüfen und zur Verbesserung beitragen.

Die Erstellung erfolgte in mehreren Stufen: Neun deutschsprachige Korpora wurden zusammengeführt und normalisiert, anschließend mit einem KI-Sprachmodell nach offiziellen Scrabble-Regeln klassifiziert und abschließend morphologisch erweitert. Details zur Methodik finden sich weiter unten auf Englisch.

---

## The word list

The primary output is `wordlist_accepted.jsonl` — one JSON object per line:

```jsonc
{"word": "laufen", "description": "Verb — sich zu Fuß fortbewegen.", "base": null, "corpus_sources": ["wiktionary","wikipedia","wortschatz"], "dict_source_count": 3, "classification_pass": "double-pass-agree", "source": "llm", "verified_by": "deepseek-chat"}
{"word": "lief", "description": "Präteritum von laufen.", "base": "laufen", "corpus_sources": ["wikipedia","wortschatz"], "dict_source_count": 1, "classification_pass": "double-pass-agree", "source": "llm", "verified_by": "deepseek-chat"}
{"word": "liefe", "description": null, "base": "laufen", "corpus_sources": [], "dict_source_count": 0, "classification_pass": null, "source": "morphology", "verified_by": "kaikki+deepseek-chat"}
```

**Fields:**

| Field | Description |
|-------|-------------|
| `word` | Lowercase word form (letters a–z, ä, ö, ü, ß only; length 2–9) |
| `description` | German dictionary-style description (null for morphology-only entries) |
| `base` | Lemma/infinitive if this is an inflected form; null for lemmas |
| `corpus_sources` | Which sourcing corpora attested this word |
| `dict_source_count` | How many dictionary sources (Wiktionary, hunspell, OpenThesaurus) contained it |
| `classification_pass` | `"double-pass-agree"` or `"tiebreaker"` |
| `source` | `"llm"` (classified by LLM), `"morphology"` (inflected form from verified lemma), `"curated"` (manual) |
| `verified_by` | `"deepseek-chat"`, `"kaikki+deepseek-chat"`, or `"manual"` |

Current word counts and length distributions are in [`stats.json`](stats.json), which is auto-generated on every push via GitHub Actions.

---

## License

**CC0 1.0 Universal (Public Domain Dedication)**

The word list is dedicated to the public domain. See [LICENSE](LICENSE).

**Source data used during construction** (not distributed):
- Kaikki Wiktionary JSONL — CC-BY-SA
- Wikipedia DE — CC-BY-SA
- Project Gutenberg DE — Public domain
- OpenThesaurus — LGPL
- hunspell de_DE (igerman98) — LGPL/GPL
- Leipzig Wortschatz — Academic free use

We use only factual word forms, not creative expression (definitions, prose). The compiled list of word forms itself has no copyright claim under *Feist v. Rural* and analogous European doctrine.

---

## Scrabble rules

The rules used to determine which words are valid are documented in [`REGELN.md`](REGELN.md) (in German), based on the official ORZ rules published by Scrabble Deutschland e.V.

---

## How spielwoerter was built

### Stage 1: Candidate sourcing

We assembled ~970K candidate words (2–9 letters, lowercase, only a–z + ä/ö/ü/ß) from nine freely-licensed German sources:

| Source | Notes |
|--------|-------|
| Kaikki Wiktionary (headwords) | German entries only |
| Kaikki Wiktionary (inflected forms) | Parsed from `forms` array |
| hunspell de_DE | Full `.aff` rule expansion via spylls |
| Wikipedia DE | Page titles + article extracts |
| Project Gutenberg DE | 25 books |
| OpenThesaurus | German thesaurus |
| Leipzig Wortschatz | Two 1M-word corpora (web + news) |
| NE contractions | Rule-based `*Cene → *Cne` forms; applied last |

Each word is tagged with which sources attested it. The raw candidate set had ~84.5% recall against the authoritative Scrabble3D German tournament list (~184K words) at a precision of only ~16% — most candidates were proper nouns, abbreviations, or foreign words.

### Stage 2: LLM classification

All ~966K candidates were classified by three independent passes of [DeepSeek V3](https://www.deepseek.com/) (temperature 0.3, batches of 10 words), applying the ORZ Scrabble rules:

- **Pass 1A** — all words in normal batch order
- **Pass 1B** — all words in reversed order (different batch context per word)
- **Both agree** → high-confidence verdict, stored immediately
- **Disagree (~6%)** → **Pass 1C (tiebreaker)**: a third independent call, verdict is final

The LLM received only the word string — no source provenance, no frequency data. Each verdict includes a German dictionary-style description and, for inflected forms, the base lemma. Words where any pass returned `uncertain: true` were excluded from the main list and collected in `wordlist_uncertain.jsonl`.

A few design choices worth noting:

- **No Tier 1 auto-accept.** Multi-source dictionary matching (≥2 sources) achieves only ~71% precision — too many non-German Wiktionary entries slip through. Everything goes through the LLM.
- **No source provenance in LLM input.** Providing dictionary-source counts biased the model toward accepting entries from non-German Wiktionary sections.
- **DeepSeek over Claude for bulk classification.** At $0.28/M input tokens with aggressive prompt caching, DeepSeek V3 cost ~4× less than Claude Sonnet for equivalent quality. Total classification cost: ~$65 for all 966K words.
- **Temperature 0.3** reduces the Pass 1A/1B disagreement rate from ~8.5% to ~6.2%, meaning fewer tiebreaker calls with no recall cost.

### Stage 3: Morphological expansion

Accepted lemmas were expanded to all inflected forms using the Kaikki Wiktionary JSONL. For each accepted word, we resolved its Kaikki headword(s) via the LLM-provided `base` field, direct headword lookup, or reverse form-to-headword lookup — then emitted all valid forms (2–9 chars, letters only, non-obsolete). Net-new forms not already in the accepted set were added with `source: "morphology"`, each with its trigger word recorded in the `base` field.

This added roughly 15% more word forms, increasing oracle recall by ~6.6 percentage points.

### Stage 4: Manual curation of short words

Two-letter and three-letter words are disproportionately important in word games and are also where LLM classification is least reliable — it tends to over-accept abbreviations and country codes. These were replaced with curated authoritative lists (75 two-letter, 661 three-letter words) compiled from ORZ official sources.

### Quality measurement

Quality was measured throughout using a black-box oracle (`scripts/oracle/wordlist_oracle.py`) that compares candidate lists against the authoritative Scrabble3D German tournament list and returns only aggregate precision/recall metrics — never individual word verdicts. The oracle is deliberately blind to individual decisions to avoid leaking the reference list.

---

## Repository structure

```
wordlist_accepted.jsonl   # PRIMARY OUTPUT — accepted words with metadata
wordlist_uncertain.jsonl  # Words flagged as uncertain (not in accepted list)
stats.json                # Auto-generated statistics
REGELN.md                 # Official Scrabble rules (German)
scripts/
  generate_stats.py       # Generates stats.json from wordlist_accepted.jsonl
  build_wordlists.py      # Assembles final JSONL wordlists from TSV + expanded forms
  oracle/
    wordlist_oracle.py    # Black-box oracle (downloads reference dict on first use)
  classify/
    calibrate.py          # Calibration runner and full production classifier
    tier2_llm.py          # LLM client — multi-provider, triple-pass, checkpointing
    prompts/
      tier2_system.txt    # German-language system prompt with ORZ Scrabble rules
  morphology/
    expand.py             # Morphological expansion via Kaikki Wiktionary JSONL
  sourcing/
    pipeline.py           # Candidate sourcing pipeline orchestrator
    normalize.py          # Word normalization (unicode, umlaut handling)
    deduplicate.py        # Cross-source deduplication and provenance tagging
    downloaders/          # Per-source download + extraction scripts
data/
  calibration_100.txt     # Fixed 100-word stratified calibration set
  (everything else)       # gitignored — generated by pipeline or calibration runs
```

---

## Reproducing the word list

### Requirements

```bash
pip install -r requirements.txt
pip install spylls  # hunspell affix expansion
```

API keys in `keys.env` (gitignored):
```
DEEPSEEK_API_KEY=...
ANTHROPIC_API_KEY=...   # optional — used for Sonnet tiebreaker variant
```

### Stage 1: Candidate sourcing

```bash
# Downloads all sources (~1–2 GB) and merges them
python3 -m scripts.sourcing.pipeline

# Re-merge only (sources already downloaded)
python3 -m scripts.sourcing.pipeline --skip-download
```

### Stage 2: LLM classification

```bash
# Quick 100-word calibration (no API cost, for prompt testing)
python3 -m scripts.classify.calibrate

# Oracle-comparable sample run (~1000 words, ~$0.06)
python3 -m scripts.classify.calibrate \
    --fraction 1000 --nonce test1 \
    --model deepseek-chat --double-haiku --tiebreaker --temperature 0.3

# Full production run (966K words, ~$65)
python3 -m scripts.classify.calibrate \
    --fraction 1 --nonce gosd_full \
    --model deepseek-chat --double-haiku --tiebreaker --temperature 0.3
```

All runs checkpoint immediately — re-running the same command resumes from where it left off.

### Stage 3: Morphological expansion

```bash
python3 -m scripts.morphology.expand \
    --tsv data/calibration_frac1_gosd_full_deepseek_t0p3_double_results.tsv \
    --output data/morphology_expanded_full.txt
```

### Build final wordlists

```bash
python3 -m scripts.build_wordlists
```

Outputs `wordlist_accepted.jsonl` and `wordlist_uncertain.jsonl` at the repo root, and `data/wordlist_rejected.jsonl` (gitignored, too large to track).

### Oracle validation

The oracle downloads the reference dictionary automatically on first use:

```bash
jq -r '.word | ascii_upcase' wordlist_accepted.jsonl | \
    python3 scripts/oracle/wordlist_oracle.py --language deutsch
```

---

## Related word lists

Before building spielwoerter, we investigated the existing German word lists. Here is what we found and why none of them could serve as a foundation.

### SuperDic — Scrabble Deutschland e.V. / Scrabble3D

The de-facto authoritative German Scrabble word list, maintained by Gero Illing and based on the Duden 29th edition. Used in all official German tournament play and bundled with the [Scrabble3D](https://scrabble3d.info/) open-source game.

**Why we didn't use it:** The license explicitly restricts use to Scrabble3D: *"Nutzung und freie Verbreitung ausschließlich zusammen mit dem Programm Scrabble 3D gestattet; kommerzieller Gebrauch untersagt."* (Use and free distribution exclusively with Scrabble 3D; commercial use prohibited.) This makes it legally unusable as a basis for a new word list. We do use it as a black-box benchmark via the oracle — measuring our recall against it without reading the individual words.

### Scrabble Deutschland e.V. Turnier-Checker

The SDeV offers an [online tournament checker](https://scrabble-info.de/wortlisten/turnier-checker/) and a SuperDic-based checker for verifying individual words. The underlying word list is the same as SuperDic above and carries the same license restriction. No downloadable, freely-licensed version exists.

### ENZ German Wordlist (gottcode/tanglet)

A CC0-licensed German word list maintained by [gottcode](https://github.com/gottcode/tanglet), used primarily by the Tanglet letter game. Contains ~676K words, broadly following Scrabble rules.

**Why we didn't use it:** Unclear source of words, no clear methodology. 

### Hippler fork of ENZ

A community fork of the ENZ list with additional words and corrections. Same CC0 license. Carries the same issues as ENZ.

---

## Contributing

Community curation happens at [spielwoerter.de](https://spielwoerter.de/). If you find words that are wrongly accepted or rejected, please submit feedback there.

For issues with the pipeline or data files, open an issue on this repository.
