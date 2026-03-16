"""
Tier 2: LLM classification of German word candidates.

Supports multiple providers:
  - Anthropic (claude-* models)  — prompt caching via cache_control
  - DeepSeek  (deepseek-*)       — OpenAI-compatible endpoint; auto context caching
  - Google    (gemini-*)         — google-genai SDK

Response schema per word:
  {
    "word":        str,   # always
    "valid":       bool,  # always
    "description": str,   # always — brief explanation, stored as permanent metadata
    "base":        str,   # optional — base form (infinitive/nominative, lowercase)
    "uncertain":   bool   # optional — present and true when genuinely unsure
  }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
from pathlib import Path

import anthropic
from tqdm import tqdm

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    """Load KEY=value pairs from keys.env or .env in project root into os.environ."""
    for name in ("keys.env", ".env"):
        env_file = _PROJECT_ROOT / name
        if not env_file.exists():
            continue
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        break


_load_env_file()

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_BATCH_SIZE = 10
MAX_RETRIES = 5
INITIAL_BACKOFF_SEC = 2.0

# Debug: set DEBUG_INJECT_BUDGET_ERROR_EVERY=N to simulate a budget-exhausted error
# on every Nth batch (e.g. N=50 → fires at batch 50, 100, 150 …). 0 = disabled.
_DEBUG_BUDGET_ERROR_EVERY: int = int(os.environ.get("DEBUG_INJECT_BUDGET_ERROR_EVERY", "0"))
_debug_batch_count: int = 0


class BudgetExhaustedError(Exception):
    """Raised when the API returns an insufficient-balance / out-of-budget error."""

# Provider-appropriate concurrency defaults.
# DeepSeek: no rate limits per their docs — use high concurrency freely.
# Anthropic free tier: ~50 RPM → keep at 5 to avoid 429s.
_DEFAULT_CONCURRENCY: dict[str, int] = {
    "anthropic": 5,
    "deepseek":  50,
    "gemini":    5,
}
DEFAULT_CONCURRENCY = 5  # legacy fallback only

DICT_SOURCES = {"wiktionary", "hunspell", "openthesaurus", "kaikki_forms"}

# Pricing in $/MTok.  cache_read/cache_write only where the provider supports it.
_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00, "cache_read": 0.08,  "cache_write": 1.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "deepseek-chat":             {"input": 0.28, "output": 0.42,  "cache_read": 0.028},
    "gemini-2.5-flash-lite":     {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-lite":     {"input": 0.075, "output": 0.30},
}

# ── Provider helpers ──────────────────────────────────────────────────────────

def _provider(model: str) -> str:
    """Detect provider from model name prefix."""
    if model.startswith("deepseek"):
        return "deepseek"
    if model.startswith("gemini"):
        return "gemini"
    return "anthropic"


def _check_api_key(model: str) -> None:
    """Exit with a clear message if the required API key is missing."""
    p = _provider(model)
    key_name = {
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini":   "GEMINI_API_KEY",
    }.get(p, "ANTHROPIC_API_KEY")
    if not os.environ.get(key_name):
        print(f"Error: {key_name} not set.", file=sys.stderr)
        sys.exit(1)


def _make_client(model: str):
    """Create the appropriate (async) API client for the given model."""
    p = _provider(model)
    if p == "deepseek":
        from openai import AsyncOpenAI
        return AsyncOpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )
    if p == "gemini":
        from google import genai
        return genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return anthropic.AsyncAnthropic()


# ── Shared helpers ────────────────────────────────────────────────────────────

def load_system_prompt(prompts_dir: Path) -> str:
    return (prompts_dir / "tier2_system.txt").read_text(encoding="utf-8").strip()


def load_meta(meta_path: Path) -> dict[str, list[str]]:
    """Load word → sources mapping from candidates_meta.jsonl."""
    meta: dict[str, list[str]] = {}
    if not meta_path.exists():
        return meta
    with open(meta_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                meta[obj["word"]] = obj.get("sources", [])
            except (json.JSONDecodeError, KeyError):
                continue
    return meta


def load_candidates(path: Path) -> list[str]:
    words = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if w:
                words.append(w)
    return words


def load_done_words(results_path: Path) -> set[str]:
    done: set[str] = set()
    if not results_path.exists():
        return done
    with open(results_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["word"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def build_user_message(batch: list[str]) -> str:
    return (
        "Classify these words. Return only a JSON array, one object per word, same order:\n"
        + json.dumps(batch, ensure_ascii=False)
    )


def parse_response(content: str, expected_words: list[str]) -> list[dict]:
    content = content.strip()
    m = re.search(r"\[[\s\S]*\]", content)
    if not m:
        return _fallback(expected_words, "No JSON array in response")
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return _fallback(expected_words, "JSON parse error")
    if not isinstance(arr, list):
        return _fallback(expected_words, "Not a JSON array")

    out = []
    for i, word in enumerate(expected_words):
        if i < len(arr) and isinstance(arr[i], dict):
            obj = dict(arr[i])
            obj["word"] = obj.get("word", word)
            if "valid" not in obj:
                obj["valid"] = None
                obj["uncertain"] = True
            obj.setdefault("description", "")
            out.append(obj)
        else:
            out.append({
                "word": word,
                "valid": None,
                "uncertain": True,
                "description": "Missing in model response",
            })
    return out


def _fallback(words: list[str], reason: str) -> list[dict]:
    return [
        {"word": w, "valid": None, "uncertain": True, "description": reason}
        for w in words
    ]


def _is_transient_error(msg: str) -> bool:
    return any(x in msg for x in ("429", "503", "rate", "overload", "quota", "exhaust", "unavailable"))


def _is_budget_error(msg: str) -> bool:
    return any(x in msg for x in ("insufficient balance", "out of balance", "insufficient_balance",
                                   "payment required", "402", "no credits", "credit limit"))


# ── Provider-specific batch runners ──────────────────────────────────────────

def _compute_cost(model: str, *, input_tok: int = 0, output_tok: int = 0,
                  cache_read_tok: int = 0, cache_write_tok: int = 0) -> float:
    """Return cost in USD for a single API call given token counts."""
    p = _PRICING.get(model, {})
    return (
        input_tok      * p.get("input",        0) +
        output_tok     * p.get("output",       0) +
        cache_read_tok * p.get("cache_read",   0) +
        cache_write_tok* p.get("cache_write",  0)
    ) / 1_000_000


async def _run_batch_anthropic(
    client: anthropic.AsyncAnthropic,
    model: str,
    system_prompt: str,
    batch: list[str],
    semaphore: asyncio.Semaphore,
    temperature: float | None = None,
) -> tuple[list[dict], int, int, float]:
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                create_kwargs: dict = dict(
                    model=model,
                    max_tokens=1024,
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": build_user_message(batch)}],
                )
                if temperature is not None:
                    create_kwargs["temperature"] = temperature
                response = await client.messages.create(**create_kwargs)
                text = "".join(b.text for b in response.content if hasattr(b, "text"))
                results = parse_response(text, batch)
                parse_errors = sum(
                    1 for r in results if "parse error" in r.get("description", "").lower()
                )
                if parse_errors == len(batch) and attempt < MAX_RETRIES - 1:
                    print("\nJSON parse failure for whole batch; retrying…", file=sys.stderr)
                    await asyncio.sleep(INITIAL_BACKOFF_SEC)
                    continue
                u = response.usage
                in_tok  = u.input_tokens
                out_tok = u.output_tokens
                cache_read  = getattr(u, "cache_read_input_tokens",    0) or 0
                cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
                cost = _compute_cost(model, input_tok=in_tok, output_tok=out_tok,
                                     cache_read_tok=cache_read, cache_write_tok=cache_write)
                return results, in_tok, out_tok, cost
            except Exception as e:
                msg = str(e).lower()
                if _is_budget_error(msg):
                    raise BudgetExhaustedError(str(e))
                if _is_transient_error(msg):
                    backoff = INITIAL_BACKOFF_SEC * (2 ** attempt)
                    print(f"\nTransient error (attempt {attempt+1}/{MAX_RETRIES}); retrying in {backoff:.0f}s…", file=sys.stderr)
                    await asyncio.sleep(backoff)
                    # On last attempt fall through to _fallback below
                else:
                    raise
    return _fallback(batch, "Max retries exceeded"), 0, 0, 0.0


async def _run_batch_deepseek(
    client,
    model: str,
    system_prompt: str,
    batch: list[str],
    semaphore: asyncio.Semaphore,
    temperature: float | None = None,
) -> tuple[list[dict], int, int, float]:
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                create_kwargs: dict = dict(
                    model=model,
                    max_tokens=1024,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": build_user_message(batch)},
                    ],
                )
                if temperature is not None:
                    create_kwargs["temperature"] = temperature
                response = await client.chat.completions.create(**create_kwargs)
                text = response.choices[0].message.content or ""
                results = parse_response(text, batch)
                parse_errors = sum(
                    1 for r in results if "parse error" in r.get("description", "").lower()
                )
                if parse_errors == len(batch) and attempt < MAX_RETRIES - 1:
                    print("\nJSON parse failure for whole batch; retrying…", file=sys.stderr)
                    await asyncio.sleep(INITIAL_BACKOFF_SEC)
                    continue
                u = response.usage
                in_tok  = u.prompt_tokens
                out_tok = u.completion_tokens
                cache_hit  = getattr(u, "prompt_cache_hit_tokens",  0) or 0
                cache_miss = in_tok - cache_hit
                cost = _compute_cost(model, input_tok=cache_miss, output_tok=out_tok,
                                     cache_read_tok=cache_hit)
                return results, in_tok, out_tok, cost
            except Exception as e:
                msg = str(e).lower()
                if _is_budget_error(msg):
                    raise BudgetExhaustedError(str(e))
                if _is_transient_error(msg):
                    backoff = INITIAL_BACKOFF_SEC * (2 ** attempt)
                    print(f"\nTransient error (attempt {attempt+1}/{MAX_RETRIES}); retrying in {backoff:.0f}s…", file=sys.stderr)
                    await asyncio.sleep(backoff)
                    # On last attempt fall through to _fallback below
                else:
                    raise
    return _fallback(batch, "Max retries exceeded"), 0, 0, 0.0


async def _run_batch_gemini(
    client,
    model: str,
    system_prompt: str,
    batch: list[str],
    semaphore: asyncio.Semaphore,
    temperature: float | None = None,
) -> tuple[list[dict], int, int, float]:
    from google.genai import types
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                config_kwargs: dict = dict(
                    system_instruction=system_prompt,
                    max_output_tokens=1024,
                )
                if temperature is not None:
                    config_kwargs["temperature"] = temperature
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=build_user_message(batch),
                    config=types.GenerateContentConfig(**config_kwargs),
                )
                text = response.text or ""
                results = parse_response(text, batch)
                parse_errors = sum(
                    1 for r in results if "parse error" in r.get("description", "").lower()
                )
                if parse_errors == len(batch) and attempt < MAX_RETRIES - 1:
                    print("\nJSON parse failure for whole batch; retrying…", file=sys.stderr)
                    await asyncio.sleep(INITIAL_BACKOFF_SEC)
                    continue
                in_tok  = response.usage_metadata.prompt_token_count or 0
                out_tok = response.usage_metadata.candidates_token_count or 0
                cost = _compute_cost(model, input_tok=in_tok, output_tok=out_tok)
                return results, in_tok, out_tok, cost
            except Exception as e:
                msg = str(e).lower()
                if _is_budget_error(msg):
                    raise BudgetExhaustedError(str(e))
                if _is_transient_error(msg):
                    backoff = INITIAL_BACKOFF_SEC * (2 ** attempt)
                    print(f"\nTransient error (attempt {attempt+1}/{MAX_RETRIES}); retrying in {backoff:.0f}s…", file=sys.stderr)
                    await asyncio.sleep(backoff)
                    # On last attempt fall through to _fallback below
                else:
                    raise
    return _fallback(batch, "Max retries exceeded"), 0, 0, 0.0


async def _run_batch_async(
    client,
    model: str,
    system_prompt: str,
    batch: list[str],
    semaphore: asyncio.Semaphore,
    temperature: float | None = None,
) -> tuple[list[dict], int, int, float]:
    """Dispatch to the appropriate provider batch runner."""
    global _debug_batch_count
    _debug_batch_count += 1
    if _DEBUG_BUDGET_ERROR_EVERY > 0 and _debug_batch_count % _DEBUG_BUDGET_ERROR_EVERY == 0:
        raise BudgetExhaustedError(
            f"DEBUG: Simulated budget exhaustion at batch {_debug_batch_count}"
        )
    p = _provider(model)
    if p == "deepseek":
        return await _run_batch_deepseek(client, model, system_prompt, batch, semaphore, temperature)
    if p == "gemini":
        return await _run_batch_gemini(client, model, system_prompt, batch, semaphore, temperature)
    return await _run_batch_anthropic(client, model, system_prompt, batch, semaphore, temperature)


# ── Main async runner ─────────────────────────────────────────────────────────

async def _run_async(
    candidates_path: Path,
    results_path: Path,
    meta_path: Path,
    prompts_dir: Path,
    model: str,
    batch_size: int,
    limit: int | None,
    concurrency: int,
    system_prompt_override: str | None = None,
    temperature: float | None = None,
) -> dict:
    results_path = Path(results_path)
    results_path.parent.mkdir(parents=True, exist_ok=True)

    _check_api_key(model)

    system_prompt = (
        system_prompt_override
        if system_prompt_override is not None
        else load_system_prompt(Path(prompts_dir))
    )
    all_candidates = load_candidates(Path(candidates_path))
    if limit is not None:
        all_candidates = all_candidates[:limit]

    done = load_done_words(results_path)
    pending = [w for w in all_candidates if w not in done]

    if not pending:
        print("All words already classified.")
        return {}

    print(
        f"Classifying {len(pending):,} words "
        f"({len(done):,} already done) with {model}, "
        f"batch={batch_size}, concurrency={concurrency}"
    )

    client = _make_client(model)
    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    budget_exceeded = asyncio.Event()
    total_in = total_out = 0
    total_cost = 0.0
    stats = {"accept": 0, "reject": 0, "uncertain": 0}
    batches = [pending[i: i + batch_size] for i in range(0, len(pending), batch_size)]
    pbar = tqdm(total=len(batches), desc="Classifying")

    async def process_batch(batch: list[str]) -> None:
        nonlocal total_in, total_out, total_cost
        if budget_exceeded.is_set():
            return  # Budget exhausted — skip remaining batches without calling the API
        try:
            results, in_tok, out_tok, cost = await _run_batch_async(
                client, model, system_prompt, batch, semaphore, temperature
            )
        except BudgetExhaustedError as e:
            budget_exceeded.set()
            print(f"\nBudget exhausted: {e}", file=sys.stderr)
            return
        async with lock:
            total_in += in_tok
            total_out += out_tok
            total_cost += cost
            for rec in results:
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if rec.get("uncertain"):
                    stats["uncertain"] += 1
                elif rec.get("valid"):
                    stats["accept"] += 1
                else:
                    stats["reject"] += 1
            fout.flush()
            pbar.update(1)

    with open(results_path, "a", encoding="utf-8") as fout:
        await asyncio.gather(*[process_batch(b) for b in batches])

    pbar.close()
    print(f"\nInput tokens: {total_in:,}  Output tokens: {total_out:,}  Cost: ${total_cost:.4f}")
    print(
        f"Accept: {stats['accept']:,}  "
        f"Reject: {stats['reject']:,}  "
        f"Uncertain: {stats['uncertain']:,}"
    )
    stats["total_cost_usd"] = total_cost

    if budget_exceeded.is_set():
        done_count = len(load_done_words(results_path))
        remaining = len(all_candidates) - done_count
        print(f"\nBudget exhausted. {done_count:,} words saved, {remaining:,} remaining.")
        print("Re-run the same command to resume from checkpoint.")
        stats["budget_exhausted"] = True

    return stats


def run(
    candidates_path: Path,
    results_path: Path,
    meta_path: Path,
    prompts_dir: Path,
    *,
    model: str = DEFAULT_MODEL,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
    concurrency: int | None = None,
    # kept for backward compatibility, no longer used
    delay_sec: float = 0.0,
    system_prompt_override: str | None = None,
    temperature: float | None = None,
) -> dict:
    effective_concurrency = concurrency if concurrency is not None else _DEFAULT_CONCURRENCY.get(_provider(model), DEFAULT_CONCURRENCY)
    return asyncio.run(
        _run_async(
            candidates_path,
            results_path,
            meta_path,
            prompts_dir,
            model=model,
            batch_size=batch_size,
            limit=limit,
            concurrency=effective_concurrency,
            system_prompt_override=system_prompt_override,
            temperature=temperature,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Tier 2 LLM classification.")
    parser.add_argument("--candidates", type=Path, default=Path("data/tier2_candidates.txt"))
    parser.add_argument("--results", type=Path, default=Path("data/tier2_results.jsonl"))
    parser.add_argument("--meta", type=Path, default=Path("data/candidates_meta.jsonl"))
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "prompts",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Model to use. Prefix determines provider: "
                             "claude-* → Anthropic, deepseek-* → DeepSeek, gemini-* → Google.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=(
            "Max concurrent API requests (default: provider-appropriate — "
            "20 for DeepSeek, 5 for Anthropic/Gemini). "
            "Keep ≤20 for DeepSeek standard tier (~500 RPM)."
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="Process only first N words")
    args = parser.parse_args()

    run(
        args.candidates,
        args.results,
        args.meta,
        args.prompts_dir,
        model=args.model,
        batch_size=args.batch_size,
        concurrency=args.concurrency,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
