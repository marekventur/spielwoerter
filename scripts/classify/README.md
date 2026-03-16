# Phase 3: LLM Classification

Classifies all ~966K candidates using a triple-pass DeepSeek V3 pipeline.

## Scripts

- **`calibrate.py`** — main entry point for both calibration runs and full production classification. Supports oracle-comparable fraction sampling, checkpointing, and multi-provider inference.
- **`tier2_llm.py`** — LLM client: batch classification, prompt caching, budget-exhaustion recovery, multi-provider support (Anthropic, DeepSeek, Gemini).
- **`tier1_dictionary.py`** — experimental auto-accept for words in 2+ dictionary sources (not used in final pipeline — 71% precision insufficient).
- **`tier3_flag.py`** — extracts uncertain words from results TSV for manual review.
- **`prompts/tier2_system.txt`** — German-language system prompt encoding ORZ Scrabble rules.

## Classification pipeline

All candidates go through three passes of the same model:

1. **Pass 1A** — classify all words in normal batch order
2. **Pass 1B** — classify all words in reversed order (different batch context)
3. **Agree** → high-confidence verdict; **Disagree** → **Pass 1C (tiebreaker)** with a third independent call

Words flagged `uncertain: true` by any pass are not included in the accepted list.

## Environment

API keys in `keys.env` (gitignored) in the project root:

```
DEEPSEEK_API_KEY=...     # primary classifier
ANTHROPIC_API_KEY=...    # optional — Sonnet as alternative tiebreaker
GEMINI_API_KEY=...       # optional — Gemini as primary classifier
```

## Running

```bash
# Quick 100-word stratified run (prompt testing)
python3 -m scripts.classify.calibrate

# Oracle-comparable sample (~1000 words, ~$0.06)
python3 -m scripts.classify.calibrate \
    --fraction 1000 --nonce test1 \
    --model deepseek-chat --double-haiku --tiebreaker --temperature 0.3

# Full production run (966K words, ~$65)
python3 -m scripts.classify.calibrate \
    --fraction 1 --nonce gosd_full \
    --model deepseek-chat --double-haiku --tiebreaker --temperature 0.3
```

Runs checkpoint immediately — re-running the same command resumes from where it left off.
