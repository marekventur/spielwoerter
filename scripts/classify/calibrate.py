"""
Calibration runner for the LLM word classifier.

Modes:

  Stratified (default, 100 words):
    Selects a fixed representative sample across dict-source strata.
    Results saved to data/calibration_100.txt and reused on re-runs.

  Fraction (--fraction N --nonce X):
    Uses the oracle's hash-based filter-fraction logic to sample ~candidates/N
    words from candidates.txt (2-9 chars). Because the oracle applies the same
    hash to its reference, precision/recall metrics remain valid for this subset.
    Results saved to data/calibration_frac<N>_<nonce>*.

  Double-Haiku (--double-haiku, usable with either of the above):
    Runs Haiku twice — once in normal order, once reversed — then compares.
      Both agree accept  → accept (high confidence)
      Both agree reject  → reject (high confidence)
      Disagree (or either uncertain) → Sonnet for final verdict
    Reports disagrement rate and per-bucket oracle metrics.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from classify.tier2_llm import load_meta, run as classify_run

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
ORACLE_SCRIPT = PROJECT_ROOT.parent / "wordlist-oracle" / "wordlist-oracle.py"

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"
DEEPSEEK_MODEL = "deepseek-chat"          # DeepSeek V3
GEMINI_MODEL = "gemini-2.5-flash-lite"    # Gemini 2.5 Flash Lite


def _model_slug(model: str) -> str:
    """Short identifier derived from model name, used in file names."""
    if "haiku" in model:
        return "haiku"
    if "sonnet" in model:
        return "sonnet"
    if "deepseek" in model:
        return "deepseek"
    if "gemini" in model:
        return "gemini"
    return model.split("-")[0]


def _temp_slug(temperature: float | None) -> str:
    """Short temperature suffix for file names (empty string if using model default)."""
    if temperature is None:
        return ""
    return "_t" + f"{temperature:.1f}".replace(".", "p")

# Extra instructions appended to the system prompt when Sonnet arbitrates disagreements.
# Goal: raise the acceptance bar so Sonnet doesn't accept borderline words that Haiku split on.
ARBITRATION_SYSTEM_SUFFIX = """\

---

## Schiedsrichteraufgabe

Die folgenden Wörter wurden von zwei unabhängigen Klassifizierungsdurchläufen \
**unterschiedlich bewertet**: Ein Durchlauf akzeptierte das Wort (valid: true), \
ein anderer lehnte es ab (valid: false), oder mindestens einer war unsicher \
(uncertain: true). Diese Wörter sind bereits als Grenzfälle identifiziert.

Deine Aufgabe ist eine Schiedsrichterentscheidung. Beachte dabei:

- **Höherer Maßstab**: Nimm ein Wort nur dann an, wenn du nach sorgfältiger Prüfung \
**überzeugt** bist, dass es als Stichwort oder als grammatisch korrekte Beugungsform \
eines verzeichneten Stichworts im deutschen Wörterbuch steht. „Könnte gültig sein" \
genügt nicht.
- **Echter Zweifel → uncertain: true**: Wenn du zwischen Ablehnen und Akzeptieren \
schwankst oder keine klare Entscheidung treffen kannst, setze uncertain: true (nicht \
valid: true). Schiedsrichter-Unsicherheiten werden von einem menschlichen Prüfer \
aufgelöst.
- **Eindeutige Fälle**: Klare Eigennamen, Abkürzungen oder offensichtlich \
nicht-deutsche Zeichenfolgen bleiben valid: false ohne uncertain.
"""
DICT_SOURCES = {"wiktionary", "hunspell", "openthesaurus", "kaikki_forms"}

STRATA = [
    (40, 3, ">=3 dict sources"),
    (30, 2, "2 dict sources"),
    (20, 1, "1 dict source"),
    (10, 0, "0 dict sources (corpus-only)"),
]


# ── Word selection ────────────────────────────────────────────────────────────

def select_stratified(meta_path: Path, seed: int = 42) -> list[str]:
    """Select 100 words across dict-source strata (fixed, reproducible)."""
    rng = random.Random(seed)
    meta = load_meta(meta_path)

    by_n: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: []}
    for word, sources in meta.items():
        if not (2 <= len(word) <= 9):
            continue
        n = min(len(set(sources) & DICT_SOURCES), 3)
        by_n[n].append(word)

    selected: list[str] = []
    for count, min_n, label in STRATA:
        pool = by_n[min_n] if min_n < 3 else by_n[3]
        sample = rng.sample(pool, min(count, len(pool)))
        print(f"  {label}: {len(sample)} words sampled from {len(pool):,}")
        selected.extend(sample)
    return selected


def select_fraction(candidates_path: Path, fraction: int, nonce: str) -> list[str]:
    """Use oracle filter-fraction to get a hash-consistent word sample (lowercase)."""
    result = subprocess.run(
        [
            "python3", str(ORACLE_SCRIPT),
            "--filter-fraction",
            "--fraction", str(fraction),
            "--nonce", nonce,
        ],
        stdin=open(candidates_path, encoding="utf-8"),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"filter-fraction error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return [w.lower() for w in result.stdout.splitlines() if w.strip()]


# ── Result handling ───────────────────────────────────────────────────────────

def load_results(path: Path) -> dict[str, dict]:
    results: dict[str, dict] = {}
    if not path.exists():
        return results
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                results[rec["word"]] = rec
            except (json.JSONDecodeError, KeyError):
                continue
    return results


def merge_results(base: dict[str, dict], overlay: dict[str, dict]) -> dict[str, dict]:
    merged = dict(base)
    merged.update(overlay)
    return merged


def print_summary(results: dict[str, dict], words: list[str], label: str) -> tuple[list[str], list[str]]:
    accepted, rejected, uncertain = [], [], []
    for w in words:
        rec = results.get(w, {})
        if rec.get("uncertain"):
            uncertain.append(rec)
        elif rec.get("valid"):
            accepted.append(rec)
        else:
            rejected.append(rec)

    print(f"\n{'='*65}")
    print(f"{label}  ({len(words)} words)")
    print(f"  Valid:     {len(accepted):3d}")
    print(f"  Invalid:   {len(rejected):3d}")
    print(f"  Uncertain: {len(uncertain):3d}")

    print(f"\n--- Sample ACCEPTED (up to 15) ---")
    for rec in accepted[:15]:
        base = f"  [base: {rec['base']}]" if rec.get("base") else ""
        print(f"  {rec['word']:<18} {rec.get('description', '')[:50]}{base}")

    print(f"\n--- Sample REJECTED (up to 10) ---")
    for rec in rejected[:10]:
        print(f"  {rec['word']:<18} {rec.get('description', '')[:58]}")

    if uncertain:
        print(f"\n--- UNCERTAIN ({len(uncertain)}) ---")
        for rec in uncertain[:10]:
            print(f"  {rec['word']:<18} {rec.get('description', '')[:58]}")

    return [r["word"] for r in accepted], [r["word"] for r in uncertain]


def run_oracle(words: list[str], label: str, fraction: int = 1, nonce: str = "") -> dict:
    if not ORACLE_SCRIPT.exists():
        print(f"\nOracle not found; skipping.")
        return {}
    oracle_input = "\n".join(w.upper() for w in words) + "\n"
    args = ["python3", str(ORACLE_SCRIPT), "--language", "deutsch",
            "--fraction", str(fraction), "--nonce", nonce]
    print(f"\n--- Oracle ({label}): {len(words)} accepted words, fraction={fraction}, nonce='{nonce}' ---")
    result = subprocess.run(args, input=oracle_input, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            tp   = data.get("true_positives", 0)
            fp   = data.get("false_positives", 0)
            fn   = data.get("false_negatives", 0)
            prec = data.get("precision_pct", 0)
            rec  = data.get("recall_pct", 0)
            ref  = data.get("reference_sampled", 0)
            print(f"  Precision: {prec:.1f}%  (TP={tp}, FP={fp})")
            print(f"  Recall:    {rec:.1f}%  (TP={tp}, FN={fn}, ref_sampled={ref})")
            return data
        except json.JSONDecodeError:
            print(result.stdout)
    else:
        print(f"  Oracle error: {result.stderr[:300]}")
    return {}


def save_tsv(results: dict[str, dict], words: list[str],
             meta: dict[str, list[str]], path: Path) -> None:
    lines = ["word\tvalid\tuncertain\tdict_sources\tsources\tbase\tdescription\tmodel"]
    for w in words:
        rec = results.get(w, {})
        sources = meta.get(w, [])
        dict_sources = len(set(sources) & DICT_SOURCES)
        lines.append("\t".join([
            w,
            "ja" if rec.get("valid") else "nein",
            "ja" if rec.get("uncertain") else "",
            str(dict_sources),
            ",".join(sources),
            rec.get("base", ""),
            rec.get("description", ""),
            rec.get("_model", ""),
        ]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"TSV saved to {path}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_words_and_run(
    words: list[str],
    tmp_name: str,
    results_path: Path,
    model: str,
    model_tag: str,
    system_prompt_override: str | None = None,
    temperature: float | None = None,
    concurrency: int | None = None,
) -> tuple[dict[str, dict], float]:
    """Write words to a temp file, run classification.
    Returns (tagged_results, cost_usd)."""
    tmp = DATA_DIR / f"_calibration_{tmp_name}.txt"
    tmp.write_text("\n".join(words) + "\n", encoding="utf-8")
    stats = classify_run(
        candidates_path=tmp,
        results_path=results_path,
        meta_path=DATA_DIR / "candidates_meta.jsonl",
        prompts_dir=PROMPTS_DIR,
        model=model,
        system_prompt_override=system_prompt_override,
        temperature=temperature,
        concurrency=concurrency,
    )
    cost = stats.get("total_cost_usd", 0.0)
    budget_exhausted = stats.get("budget_exhausted", False)
    results = load_results(results_path)
    for rec in results.values():
        rec["_model"] = model_tag
    return results, cost, budget_exhausted


# ── Standard two-pass ─────────────────────────────────────────────────────────

def run_two_pass(
    words: list[str],
    meta: dict[str, list[str]],
    haiku_results_path: Path,
    sonnet_results_path: Path,
    fraction: int,
    nonce: str,
    tsv_path: Path,
    first_pass_model: str = HAIKU_MODEL,
    concurrency: int | None = None,
) -> None:
    mslug = _model_slug(first_pass_model)
    total_cost = 0.0
    print(f"\n── Pass 1: {first_pass_model} ({len(words)} words) ──")
    haiku_results, cost1, budget1 = _write_words_and_run(words, "input", haiku_results_path, first_pass_model, mslug,
                                                          concurrency=concurrency)
    total_cost += cost1
    if budget1:
        print(f"\n  Budget exhausted during Pass 1. Total cost so far: ${total_cost:.4f}")
        print("  Re-run the same command to resume from checkpoint.")
        return

    haiku_accepted, haiku_uncertain = print_summary(
        haiku_results, words, f"PASS 1 — {first_pass_model}"
    )
    run_oracle(haiku_accepted, f"{mslug} only", fraction, nonce)

    if haiku_uncertain:
        print(f"\n── Pass 2: {SONNET_MODEL} on {len(haiku_uncertain)} uncertain words ──")
        sonnet_results, cost2, budget2 = _write_words_and_run(
            haiku_uncertain, "uncertain", sonnet_results_path, SONNET_MODEL, "sonnet",
            concurrency=concurrency,
        )
        total_cost += cost2
        if budget2:
            print(f"\n  Budget exhausted during Pass 2. Total cost so far: ${total_cost:.4f}")
            print("  Re-run the same command to resume from checkpoint.")
            return
        merged = merge_results(haiku_results, sonnet_results)
        final_accepted, _ = print_summary(merged, words, "FINAL (Pass1 + Sonnet)")
        run_oracle(final_accepted, f"{mslug} + Sonnet", fraction, nonce)
        save_tsv(merged, words, meta, tsv_path)
    else:
        print("\nNo uncertain words — skipping Sonnet pass.")
        save_tsv(haiku_results, words, meta, tsv_path)
    print(f"\n💰 Total cost this run: ${total_cost:.4f}")


# ── Double-Haiku pass ─────────────────────────────────────────────────────────

def _merge_double_haiku(
    run_a: dict[str, dict],
    run_b: dict[str, dict],
    words: list[str],
) -> tuple[dict[str, dict], list[str]]:
    """
    Compare two Haiku runs word by word.
    Returns (merged_dict, disagreement_word_list).
    Agreements keep run_a's record (tagged haiku_agree).
    Disagreements are tagged haiku_disagree and queued for Sonnet.
    """
    merged: dict[str, dict] = {}
    disagreements: list[str] = []

    for w in words:
        a = run_a.get(w, {})
        b = run_b.get(w, {})
        a_valid = a.get("valid")
        b_valid = b.get("valid")
        a_unc = bool(a.get("uncertain"))
        b_unc = bool(b.get("uncertain"))

        if a_valid == b_valid and a_valid is not None and not a_unc and not b_unc:
            rec = dict(a)
            rec["_model"] = "haiku_agree"
            merged[w] = rec
        else:
            desc_a = a.get("description", "—")[:45]
            desc_b = b.get("description", "—")[:45]
            merged[w] = {
                "word": w,
                "valid": None,
                "uncertain": True,
                "description": f"[A: {desc_a}] [B: {desc_b}]",
                "_model": "haiku_disagree",
            }
            disagreements.append(w)

    return merged, disagreements


def _print_disagreement_stats(
    run_a: dict[str, dict],
    run_b: dict[str, dict],
    words: list[str],
    next_step: str = "Sonnet",
) -> None:
    agree_accept = agree_reject = 0
    av_br = ar_bv = a_unc = b_unc = both_unc = 0

    for w in words:
        a = run_a.get(w, {})
        b = run_b.get(w, {})
        av, bv = a.get("valid"), b.get("valid")
        au, bu = bool(a.get("uncertain")), bool(b.get("uncertain"))

        if av == bv and av is not None and not au and not bu:
            if av:
                agree_accept += 1
            else:
                agree_reject += 1
        elif au and bu:
            both_unc += 1
        elif au:
            a_unc += 1
        elif bu:
            b_unc += 1
        elif av and not bv:
            av_br += 1
        else:
            ar_bv += 1

    total = len(words)
    disagree = total - agree_accept - agree_reject
    print(f"\n{'='*65}")
    print(f"DISAGREEMENT ANALYSIS  ({total} words)")
    print(f"  Agree accept:  {agree_accept:4d}  ({agree_accept/total*100:.1f}%)")
    print(f"  Agree reject:  {agree_reject:4d}  ({agree_reject/total*100:.1f}%)")
    print(f"  Disagree:      {disagree:4d}  ({disagree/total*100:.1f}%)  → {next_step}")
    if disagree:
        print(f"    A=accept / B=reject:    {av_br}")
        print(f"    A=reject / B=accept:    {ar_bv}")
        print(f"    A=uncertain / B=other:  {a_unc}")
        print(f"    B=uncertain / A=other:  {b_unc}")
        print(f"    Both uncertain:         {both_unc}")


def run_double_haiku_pass(
    words: list[str],
    meta: dict[str, list[str]],
    haiku_a_path: Path,
    haiku_b_path: Path,
    sonnet_results_path: Path,
    fraction: int,
    nonce: str,
    tsv_path: Path,
    first_pass_model: str = HAIKU_MODEL,
    skip_sonnet: bool = False,
    use_tiebreaker: bool = False,
    temperature: float | None = None,
    concurrency: int | None = None,
) -> None:
    mslug = _model_slug(first_pass_model)
    total_cost = 0.0
    # Pass 1A — normal order
    print(f"\n── Pass 1A: {first_pass_model} (normal order, {len(words)} words) ──")
    run_a, cost_a, budget_a = _write_words_and_run(words, "input_a", haiku_a_path, first_pass_model, f"{mslug}_a",
                                                    temperature=temperature, concurrency=concurrency)
    total_cost += cost_a
    if budget_a:
        print(f"\n  Budget exhausted during Pass 1A. Total cost so far: ${total_cost:.4f}")
        print("  Re-run the same command to resume from checkpoint.")
        return

    # Pass 1B — reversed order (different batch neighbours for every word)
    print(f"\n── Pass 1B: {first_pass_model} (reversed order, {len(words)} words) ──")
    run_b, cost_b, budget_b = _write_words_and_run(list(reversed(words)), "input_b", haiku_b_path, first_pass_model, f"{mslug}_b",
                                                    temperature=temperature, concurrency=concurrency)
    total_cost += cost_b
    if budget_b:
        print(f"\n  Budget exhausted during Pass 1B. Total cost so far: ${total_cost:.4f}")
        print("  Re-run the same command to resume from checkpoint.")
        return

    # Disagreement analysis
    next_step = "uncertain" if skip_sonnet else ("Tiebreaker" if use_tiebreaker else "Sonnet")
    _print_disagreement_stats(run_a, run_b, words, next_step=next_step)
    merged, disagreements = _merge_double_haiku(run_a, run_b, words)

    # Oracle on agreed-accept words only (no Sonnet yet)
    agreed_accepted = [w for w in words if merged[w].get("valid") is True]
    run_oracle(agreed_accepted, "Agree-accept only (no Sonnet)", fraction, nonce)

    # Pass 1C — Tiebreaker (same model, third call on disagreements)
    if skip_sonnet:
        print(f"\n  Skipping Sonnet pass — {len(disagreements)} disagreements kept as uncertain.")
        run_oracle(agreed_accepted, f"Double {mslug} agree-accept (final)", fraction, nonce)
        save_tsv(merged, words, meta, tsv_path)
        print(f"\n  Total cost this run: ${total_cost:.4f}")
        return

    if use_tiebreaker:
        if disagreements:
            print(f"\n── Pass 1C: {first_pass_model} (tiebreaker, {len(disagreements)} words) ──")
            tie_results, cost_t, budget_t = _write_words_and_run(
                disagreements, "tiebreaker", sonnet_results_path, first_pass_model, f"{mslug}_tie",
                temperature=temperature, concurrency=concurrency,
            )
            total_cost += cost_t
            if budget_t:
                print(f"\n  Budget exhausted during Tiebreaker. Total cost so far: ${total_cost:.4f}")
                print("  Re-run the same command to resume from checkpoint.")
                return
            t_accept = sum(1 for w in disagreements if tie_results.get(w, {}).get("valid") is True)
            t_reject = sum(1 for w in disagreements
                           if tie_results.get(w, {}).get("valid") is False
                           and not tie_results.get(w, {}).get("uncertain"))
            t_unc = len(disagreements) - t_accept - t_reject
            print(f"\n  Tiebreaker resolved {len(disagreements)} disagreements:")
            print(f"    Accepted:        {t_accept}")
            print(f"    Rejected:        {t_reject}")
            print(f"    Still uncertain: {t_unc}")
            final = merge_results(merged, tie_results)
            final_accepted, _ = print_summary(final, words, f"FINAL (Double {mslug} + Tiebreaker)")
            run_oracle(final_accepted, f"Double {mslug} + Tiebreaker (final)", fraction, nonce)
            save_tsv(final, words, meta, tsv_path)
        else:
            print("\nNo disagreements — skipping tiebreaker.")
            run_oracle(agreed_accepted, f"Double {mslug} (full agree)", fraction, nonce)
            save_tsv(merged, words, meta, tsv_path)
        print(f"\n  Total cost this run: ${total_cost:.4f}")
        return

    if disagreements:
        print(f"\n── Pass 2: {SONNET_MODEL} on {len(disagreements)} disagreements ──")
        base_prompt = (PROMPTS_DIR / "tier2_system.txt").read_text(encoding="utf-8").strip()
        arbitration_prompt = base_prompt + ARBITRATION_SYSTEM_SUFFIX
        sonnet_results, cost_s, budget_s = _write_words_and_run(
            disagreements, "disagreements", sonnet_results_path, SONNET_MODEL, "sonnet",
            system_prompt_override=arbitration_prompt, concurrency=concurrency,
        )
        total_cost += cost_s
        if budget_s:
            print(f"\n  Budget exhausted during Sonnet pass. Total cost so far: ${total_cost:.4f}")
            print("  Re-run the same command to resume from checkpoint.")
            return

        s_accept = sum(1 for w in disagreements if sonnet_results.get(w, {}).get("valid") is True)
        s_reject = sum(1 for w in disagreements
                       if sonnet_results.get(w, {}).get("valid") is False
                       and not sonnet_results.get(w, {}).get("uncertain"))
        s_unc    = len(disagreements) - s_accept - s_reject
        print(f"\n  Sonnet resolved {len(disagreements)} disagreements:")
        print(f"    Accepted:        {s_accept}")
        print(f"    Rejected:        {s_reject}")
        print(f"    Still uncertain: {s_unc}")

        # Oracle on what Sonnet accepted from the disagreement set
        sonnet_accepted_words = [w for w in disagreements
                                 if sonnet_results.get(w, {}).get("valid") is True]
        if sonnet_accepted_words:
            run_oracle(sonnet_accepted_words, "Sonnet-resolved (disagreements only)", fraction, nonce)

        final = merge_results(merged, sonnet_results)
        final_accepted, _ = print_summary(final, words, f"FINAL (Double {mslug} + Sonnet)")
        run_oracle(final_accepted, f"Double {mslug} + Sonnet (final)", fraction, nonce)
        save_tsv(final, words, meta, tsv_path)
    else:
        print("\nNo disagreements — skipping Sonnet pass.")
        run_oracle(agreed_accepted, f"Double {mslug} (full agree)", fraction, nonce)
        save_tsv(merged, words, meta, tsv_path)
    print(f"\n  Total cost this run: ${total_cost:.4f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fraction", type=int, default=None,
                        help="Use oracle filter-fraction sampling (e.g. 1000 → ~1/1000 of words)")
    parser.add_argument("--nonce", type=str, default="gosd1",
                        help="Nonce for fraction sampling (default: gosd1)")
    parser.add_argument("--double-haiku", action="store_true",
                        help="Run the first-pass model twice (normal + reversed order); send disagreements to Sonnet")
    parser.add_argument("--model", default=HAIKU_MODEL,
                        help=f"First-pass model (default: {HAIKU_MODEL}). "
                             f"Also try: {DEEPSEEK_MODEL}, {GEMINI_MODEL}")
    parser.add_argument("--no-sonnet", action="store_true",
                        help="Skip Sonnet arbitration; keep disagreements as uncertain.")
    parser.add_argument("--tiebreaker", action="store_true",
                        help="Use a third call with the same model to break A/B disagreements (instead of Sonnet).")
    parser.add_argument("--temperature", type=float, default=None,
                        help="Sampling temperature for all model calls (default: use model default).")
    parser.add_argument("--concurrency", type=int, default=None,
                        help="Max concurrent API requests (default: 50 for DeepSeek [no rate limit], 5 for Anthropic/Gemini).")
    args = parser.parse_args()

    meta_path = DATA_DIR / "candidates_meta.jsonl"
    meta = load_meta(meta_path)

    if args.fraction is not None:
        slug = f"frac{args.fraction}_{args.nonce}"
        words_path = DATA_DIR / f"calibration_{slug}.txt"

        if words_path.exists():
            print(f"Using existing sample: {words_path}")
            words = [w for w in words_path.read_text(encoding="utf-8").splitlines() if w]
        else:
            print(f"Sampling with fraction={args.fraction}, nonce='{args.nonce}'...")
            words = select_fraction(DATA_DIR / "candidates.txt", args.fraction, args.nonce)
            words_path.write_text("\n".join(words) + "\n", encoding="utf-8")
            print(f"Sampled {len(words)} words → {words_path}")

        mslug = _model_slug(args.model) + _temp_slug(args.temperature)
        third_pass_label = "tiebreaker" if args.tiebreaker else "sonnet"
        if args.double_haiku:
            run_double_haiku_pass(
                words, meta,
                haiku_a_path=DATA_DIR / f"calibration_{slug}_{mslug}_double_a.jsonl",
                haiku_b_path=DATA_DIR / f"calibration_{slug}_{mslug}_double_b.jsonl",
                sonnet_results_path=DATA_DIR / f"calibration_{slug}_{mslug}_double_{third_pass_label}.jsonl",
                fraction=args.fraction,
                nonce=args.nonce,
                tsv_path=DATA_DIR / f"calibration_{slug}_{mslug}_double_results.tsv",
                first_pass_model=args.model,
                skip_sonnet=args.no_sonnet,
                use_tiebreaker=args.tiebreaker,
                temperature=args.temperature,
                concurrency=args.concurrency,
            )
        else:
            run_two_pass(
                words, meta,
                haiku_results_path=DATA_DIR / f"calibration_{slug}_{mslug}.jsonl",
                sonnet_results_path=DATA_DIR / f"calibration_{slug}_{mslug}_sonnet.jsonl",
                fraction=args.fraction,
                nonce=args.nonce,
                tsv_path=DATA_DIR / f"calibration_{slug}_{mslug}_results.tsv",
                first_pass_model=args.model,
                concurrency=args.concurrency,
            )

    else:
        words_path  = DATA_DIR / "calibration_100.txt"
        tsv_path    = DATA_DIR / "calibration_100_results.tsv"

        if words_path.exists():
            print(f"Using existing calibration set: {words_path}")
            words = [w for w in words_path.read_text(encoding="utf-8").splitlines() if w]
        else:
            print("Selecting calibration words...")
            words = select_stratified(meta_path)
            words_path.write_text("\n".join(words) + "\n", encoding="utf-8")
            print(f"Saved {len(words)} words to {words_path}")

        mslug = _model_slug(args.model) + _temp_slug(args.temperature)
        third_pass_label = "tiebreaker" if args.tiebreaker else "sonnet"
        if args.double_haiku:
            run_double_haiku_pass(
                words, meta,
                haiku_a_path=DATA_DIR / f"calibration_100_{mslug}_double_a.jsonl",
                haiku_b_path=DATA_DIR / f"calibration_100_{mslug}_double_b.jsonl",
                sonnet_results_path=DATA_DIR / f"calibration_100_{mslug}_double_{third_pass_label}.jsonl",
                fraction=1,
                nonce="",
                tsv_path=DATA_DIR / f"calibration_100_{mslug}_double_results.tsv",
                first_pass_model=args.model,
                skip_sonnet=args.no_sonnet,
                use_tiebreaker=args.tiebreaker,
                temperature=args.temperature,
                concurrency=args.concurrency,
            )
        else:
            run_two_pass(
                words, meta,
                haiku_results_path=DATA_DIR / f"calibration_100_{mslug}.jsonl",
                sonnet_results_path=DATA_DIR / f"calibration_100_{mslug}_sonnet.jsonl",
                fraction=1,
                nonce="",
                tsv_path=DATA_DIR / f"calibration_100_{mslug}_results.tsv",
                first_pass_model=args.model,
                concurrency=args.concurrency,
            )


if __name__ == "__main__":
    main()
