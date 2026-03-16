"""
Download German Hunspell dictionary (de_DE) from LanguageTool mirror of igerman98.
Performs full affix expansion using the .aff rules file to generate all valid
inflected forms (conjugations, declensions, etc.), not just stems.
"""
from __future__ import annotations

import re
from pathlib import Path

import requests

DE_DE_DIC_URL = (
    "https://raw.githubusercontent.com/languagetool-org/languagetool/master/"
    "languagetool-language-modules/de/src/main/resources/org/languagetool/"
    "resource/de/hunspell/de_DE.dic"
)
DE_DE_AFF_URL = (
    "https://raw.githubusercontent.com/languagetool-org/languagetool/master/"
    "languagetool-language-modules/de/src/main/resources/org/languagetool/"
    "resource/de/hunspell/de_DE.aff"
)

# Valid German word: only a-z plus umlauts and ß, 2–15 chars
VALID_WORD = re.compile(r"^[a-zA-ZäöüÄÖÜß]{2,15}$")


def _expand(raw_dir: Path) -> set[str]:
    """Load de_DE.dic + de_DE.aff via spylls and expand all affix rules."""
    try:
        from spylls.hunspell import Dictionary
    except ImportError as e:
        raise ImportError("spylls is required for affix expansion: pip install spylls") from e

    d = Dictionary.from_files(str(raw_dir / "de_DE"))
    aff = d.aff
    NEEDAFFIX = aff.NEEDAFFIX    # stems that require an affix to be valid
    ONLYINCPD = aff.ONLYINCOMPOUND  # stems only valid inside compounds

    forms: set[str] = set()

    for word in d.dic.words:
        stem = word.stem
        flags = word.flags

        # Skip compound-only stems and skip stems starting with '#' (comments)
        if stem.startswith("#") or ONLYINCPD in flags:
            continue

        # Emit stem itself unless it needs an affix
        if NEEDAFFIX not in flags and VALID_WORD.match(stem):
            forms.add(stem.lower())

        # Collect crossproduct-eligible sfx forms for later pfx combination
        cross_sfx: list[tuple[str, object]] = []  # (derived_form, sfx_rule)

        # --- Apply suffix rules ---
        for flag in flags:
            if flag not in aff.SFX:
                continue
            for rule in aff.SFX[flag]:
                if not rule.cond_regexp.search(stem):
                    continue
                base = stem[: -len(rule.strip)] if rule.strip else stem
                derived = base + rule.add
                if VALID_WORD.match(derived):
                    forms.add(derived.lower())
                if rule.crossproduct:
                    cross_sfx.append((derived, rule))

        # --- Apply prefix rules (standalone + crossproduct with sfx) ---
        for flag in flags:
            if flag not in aff.PFX:
                continue
            for prule in aff.PFX[flag]:
                if not prule.cond_regexp.search(stem):
                    continue
                pbase = stem[len(prule.strip) :] if prule.strip else stem
                pform = prule.add + pbase
                if VALID_WORD.match(pform):
                    forms.add(pform.lower())

                # Crossproduct: combine this prefix with all eligible sfx forms
                if prule.crossproduct:
                    for sfx_form, srule in cross_sfx:
                        # Re-derive the combined form from the original stem:
                        # strip pfx.strip from start, strip sfx.strip from end, add both affixes
                        if srule.strip:
                            mid = stem[len(prule.strip) : -len(srule.strip)]
                        else:
                            mid = stem[len(prule.strip) :]
                        cross = prule.add + mid + srule.add
                        if VALID_WORD.match(cross):
                            forms.add(cross.lower())

    return forms


def download(raw_dir: Path) -> Path:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dic_path = raw_dir / "de_DE.dic"
    aff_path = raw_dir / "de_DE.aff"
    out_file = raw_dir / "words.txt"

    if not dic_path.exists():
        r = requests.get(DE_DE_DIC_URL)
        r.raise_for_status()
        dic_path.write_text(r.text, encoding="utf-8")

    if not aff_path.exists():
        r = requests.get(DE_DE_AFF_URL)
        r.raise_for_status()
        aff_path.write_bytes(r.content)

    print("  Expanding hunspell affix rules (this may take a few minutes)...")
    words = _expand(raw_dir)
    words_sorted = sorted(words)
    out_file.write_text("\n".join(words_sorted) + "\n", encoding="utf-8")
    print(f"  -> {len(words_sorted)} expanded forms written to {out_file}")
    return out_file
