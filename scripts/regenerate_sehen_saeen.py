"""
One-off data fix (2026-09): rebuild the forms of the verbs on -sehen and -säen.

The Kaikki/Wiktionary tables behind the morphology expansion are mostly empty
for compound verbs, so many plain forms ("aufsiehst", "aussehn") never made it
into the list, and the LLM pass that labelled the rest mixed verbs up (forms of
aussehen filed under aussäen, forms of aussinnen filed under aussäen, bases
like "besah" or "besaen"). Reported by moderator Panikpilz, who also supplied
the infinitives with their separability (scripts/data/verben_sehen.txt,
scripts/data/verben_saeen.txt).

Both paradigms are fully regular once the principal parts are known, so the
script derives every form by rule (REGELN.md, "Verben"), keeps the ones with
2 to 9 letters and compares them with the three lists:

  add       form is in no list                         -> accepted
  unblock   form is in rejected or uncertain           -> accepted
  relabel   form is accepted under a wrong base        -> base/description fixed
  remove    accepted "form" of these verbs that no rule produces -> rejected

Only form types that already occur in the moderated list for comparable verbs
are generated. Not generated at all: comparatives of participles, the Gerundiv
(every one has 10+ letters), joined imperatives of separable verbs ("absieh"),
"-siehe" for prefixed verbs and the archaic "sahest"/"sahet".

Two further types are rule-conform on a plain reading of REGELN.md but have no
precedent in the list, so they are behind switches until the moderators decide:

  --with-seh     1st person singular with e-Tilgung: seh, abseh, beseh ...
                 ("seh" and "geb" are curated rejections; "nehm", "treff",
                 "einseh" and "wiederseh" are accepted)
  --with-past-n  -en after vowel in Präteritum/Konjunktiv II: sahn, sähn, absahn ...
                 (REGELN.md names "1./3. Person Plural" without a tense; the list
                 has freun/sehn/sän but no flohn, liehn, geschahn)

Usage:
    python3 scripts/regenerate_sehen_saeen.py            # rewrite the lists
    python3 scripts/regenerate_sehen_saeen.py --dry-run  # only print the report
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPTED = ROOT / "wordlist_accepted.jsonl"
UNCERTAIN = ROOT / "wordlist_uncertain.jsonl"
REJECTED = ROOT / "wordlist_rejected.jsonl"
DATA = ROOT / "scripts" / "data"

MIN_LEN, MAX_LEN = 2, 9
ADJ = ("e", "em", "en", "er", "es")

# Partizip II may only be declined for transitive verbs (REGELN.md). Only verbs
# whose declined participle can fit into 9 letters need a decision at all.
TRANSITIVE = {
    "sehen", "absehen", "ansehen", "besehen", "ersehen", "versehen", "übersehen",
    "säen", "ansäen", "aussäen", "besäen", "einsäen", "übersäen",
}

# Lemmas from the supplied lists that are not in the list yet need a real description.
LEMMA_DESCRIPTIONS = {
    "festsehen": "Verb — sich festsehen: den Blick nicht mehr abwenden können",
}

# Accepted entries filed under these verbs that are not forms of them.
INVALID = {
    "sähle": ("sehen", "Keine Form von sehen (Konjunktiv II: sähe, sähest, sähen, sähet)."),
}

# Valid words that were filed under a verb of these families by mistake.
FIX_BASE = {
    "aussännen": ("aussinnen", "1./3. Person Plural Konjunktiv II von aussinnen"),
    "aussännet": ("aussinnen", "2. Person Plural Konjunktiv II von aussinnen"),
    "seihtest": ("seihen", "2. Person Singular Präteritum von seihen"),
    "seihtet": ("seihen", "2. Person Plural Präteritum von seihen"),
}

# Same rule ("Endung -en nach Vokal"), other verbs: removed in May/June 2026
# together with gesehn and zusehn, to be restored with them.
EXTRA_UNBLOCK = {
    "gehn": ("gehen", "Infinitiv sowie 1./3. Person Plural Präsens (mit e-Tilgung nach Vokal)"),
    "stehn": ("stehen", "Infinitiv sowie 1./3. Person Plural Präsens (mit e-Tilgung nach Vokal)"),
    "drehn": ("drehen", "Infinitiv sowie 1./3. Person Plural Präsens (mit e-Tilgung nach Vokal)"),
    "drohn": ("drohen", "Infinitiv sowie 1./3. Person Plural Präsens (mit e-Tilgung nach Vokal)"),
    "fliehn": ("fliehen", "Infinitiv sowie 1./3. Person Plural Präsens (mit e-Tilgung nach Vokal)"),
    "haun": ("hauen", "Infinitiv sowie 1./3. Person Plural Präsens (mit e-Tilgung nach Vokal)"),
}


class Forms(dict):
    """form -> description fragment; a second function of the same spelling is appended."""

    def put(self, form: str, desc: str) -> None:
        if form in self:
            if desc not in self[form]:
                self[form] += " sowie " + desc
        else:
            self[form] = desc


def read_verbs(path: Path) -> list[tuple[str, bool]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        parts = [p.strip() for p in line.split(";")]
        if len(parts) >= 2 and parts[0]:
            out.append((parts[0], parts[1] == "ja"))
    return out


def sehen_forms(lemma: str, separable: bool, with_seh: bool, with_past_n: bool) -> Forms:
    p = lemma[: -len("sehen")]
    f = Forms()
    f.put(p + "sehen", "Infinitiv")
    f.put(p + "sehn", "Infinitiv sowie 1./3. Person Plural Präsens (mit e-Tilgung nach Vokal)")
    f.put(p + "sehe", "1. Person Singular Präsens")
    if with_seh:
        f.put(p + "seh", "1. Person Singular Präsens (mit e-Tilgung)")
    f.put(p + "siehst", "2. Person Singular Präsens")
    f.put(p + "sieht", "3. Person Singular Präsens")
    f.put(p + "seht", "2. Person Plural Präsens")
    f.put(p + "sehest", "2. Person Singular Konjunktiv I")
    f.put(p + "sehet", "2. Person Plural Konjunktiv I")
    f.put(p + "sah", "1./3. Person Singular Präteritum")
    f.put(p + "sahst", "2. Person Singular Präteritum")
    f.put(p + "sahen", "1./3. Person Plural Präteritum")
    f.put(p + "saht", "2. Person Plural Präteritum")
    f.put(p + "sähe", "1./3. Person Singular Konjunktiv II")
    f.put(p + "säh", "1./3. Person Singular Konjunktiv II (mit e-Tilgung)")
    f.put(p + "sähest", "2. Person Singular Konjunktiv II")
    f.put(p + "sähst", "2. Person Singular Konjunktiv II")
    f.put(p + "sähen", "1./3. Person Plural Konjunktiv II")
    f.put(p + "sähet", "2. Person Plural Konjunktiv II")
    f.put(p + "säht", "2. Person Plural Konjunktiv II")
    if with_past_n:
        f.put(p + "sahn", "1./3. Person Plural Präteritum (mit e-Tilgung nach Vokal)")
        f.put(p + "sähn", "1./3. Person Plural Konjunktiv II (mit e-Tilgung nach Vokal)")
    f.put(p + "sehens", "Genitiv des substantivierten Infinitivs")
    f.put(p + "sehend", "Partizip I")
    for e in ADJ:
        f.put(p + "sehend" + e, "Partizip I, dekliniert")
    if not separable:
        f.put(p + "sieh", "Imperativ Singular")
        if p == "":
            f.put("siehe", "Imperativ Singular")
    # "ausersehen" carries an inseparable second prefix: no ge-, zu goes in the middle.
    if separable and lemma != "ausersehen":
        f.put(p + "zusehen", "Infinitiv mit zu")
        f.put(p + "zusehn", "Infinitiv mit zu (mit e-Tilgung nach Vokal)")
    ge = "ge" if (separable or p == "") and lemma != "ausersehen" else ""
    full, short = p + ge + "sehen", p + ge + "sehn"
    f.put(full, "Partizip II")
    f.put(short, "Partizip II (mit e-Tilgung nach Vokal)")
    if lemma in TRANSITIVE:
        for e in ADJ:
            f.put(full + e, "Partizip II, dekliniert")
            f.put(short + e, "Partizip II, dekliniert (mit e-Tilgung)")
    return f


def saeen_forms(lemma: str, separable: bool) -> Forms:
    p = lemma[: -len("säen")]
    f = Forms()
    f.put(p + "säen", "Infinitiv")
    f.put(p + "sän", "Infinitiv sowie 1./3. Person Plural Präsens (mit e-Tilgung nach Vokal)")
    f.put(p + "säe", "1. Person Singular Präsens")
    f.put(p + "sä", "1. Person Singular Präsens (mit e-Tilgung)")
    f.put(p + "säst", "2. Person Singular Präsens")
    f.put(p + "sät", "3. Person Singular und 2. Person Plural Präsens")
    f.put(p + "säest", "2. Person Singular Konjunktiv I")
    f.put(p + "säet", "2. Person Plural Konjunktiv I")
    f.put(p + "säte", "1./3. Person Singular Präteritum")
    f.put(p + "sätest", "2. Person Singular Präteritum")
    f.put(p + "säten", "1./3. Person Plural Präteritum")
    f.put(p + "sätet", "2. Person Plural Präteritum")
    f.put(p + "säens", "Genitiv des substantivierten Infinitivs")
    f.put(p + "säend", "Partizip I")
    for e in ADJ:
        f.put(p + "säend" + e, "Partizip I, dekliniert")
    if not separable:
        f.put(p + "säe", "Imperativ Singular")
        f.put(p + "sä", "Imperativ Singular (mit e-Tilgung)")
    if separable:
        f.put(p + "zusäen", "Infinitiv mit zu")
        f.put(p + "zusän", "Infinitiv mit zu (mit e-Tilgung nach Vokal)")
    pii = p + ("ge" if (separable or p == "") else "") + "sät"
    f.put(pii, "Partizip II")
    if lemma in TRANSITIVE:
        for e in ADJ:
            f.put(pii + e, "Partizip II, dekliniert")
    return f


def paradigm(with_seh: bool, with_past_n: bool) -> dict[str, list[tuple[str, str]]]:
    """form -> [(lemma, description fragment)], every lemma that yields it."""
    sehen = read_verbs(DATA / "verben_sehen.txt")
    saeen = read_verbs(DATA / "verben_saeen.txt")
    if not any(l == "säen" for l, _ in saeen):
        saeen.insert(0, ("säen", False))  # the base verb is missing from the supplied file

    out: dict[str, list[tuple[str, str]]] = {}
    for family, verbs in (("sehen", sehen), ("säen", saeen)):
        for lemma, sep in verbs:
            forms = sehen_forms(lemma, sep, with_seh, with_past_n) if family == "sehen" else saeen_forms(lemma, sep)
            for form, desc in forms.items():
                if not MIN_LEN <= len(form) <= MAX_LEN:
                    continue
                hits = out.setdefault(form, [])
                same = [i for i, (l, _) in enumerate(hits) if l == lemma]
                if same:  # übersehen is listed twice, separable and inseparable
                    if desc not in hits[same[0]][1]:
                        hits[same[0]] = (lemma, hits[same[0]][1] + " sowie " + desc)
                else:
                    hits.append((lemma, desc))
    return out


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def dump(path: Path, rows: list[dict]) -> None:
    # Same shape as lib/sync.ts toJsonl(): one JSON.stringify() per line.
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def insert_sorted(rows: list[dict], entry: dict) -> None:
    # Mirrors insertSorted() in lib/sync.ts: before the first word that sorts after it.
    for i, r in enumerate(rows):
        if r["word"] > entry["word"]:
            rows.insert(i, entry)
            return
    rows.append(entry)


def describe(form: str, hits: list[tuple[str, str]]) -> str:
    if form in LEMMA_DESCRIPTIONS:
        return LEMMA_DESCRIPTIONS[form]
    return "; ".join(f"{desc} von {lemma}" for lemma, desc in hits)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-seh", action="store_true")
    ap.add_argument("--with-past-n", action="store_true")
    args = ap.parse_args()

    accepted, uncertain, rejected = load(ACCEPTED), load(UNCERTAIN), load(REJECTED)
    acc = {r["word"]: r for r in accepted}
    unc = {r["word"]: r for r in uncertain}
    rej = {r["word"]: r for r in rejected}
    forms = paradigm(args.with_seh, args.with_past_n)
    lemmas = {l for hits in forms.values() for l, _ in hits}

    add, unblock, relabel = [], [], []
    bad_bases: set[str] = set()
    for form, hits in sorted(forms.items()):
        ok_bases = {l for l, _ in hits}
        if form in acc:
            base = acc[form].get("base")
            # Lemmas and words with a sense of their own (base None) keep their entry.
            if base is None or base in ok_bases or form in lemmas:
                continue
            # Filed under another verb of these families, or under a non-lemma form.
            if base in lemmas or base not in acc or acc[base].get("base") is not None:
                relabel.append((form, base, hits))
                bad_bases.add(base)
        elif form in rej or form in unc:
            unblock.append((form, hits))
        else:
            add.append((form, hits))
    extra = [(w, [(l, d)]) for w, (l, d) in EXTRA_UNBLOCK.items() if w in rej and w not in acc]
    fix_base = [(w, l, d) for w, (l, d) in FIX_BASE.items() if w in acc and l in acc and acc[w].get("base") != l]
    remove = [(w, l, why) for w, (l, why) in INVALID.items() if w in acc]

    # Accepted entries that hang off these verbs but that no rule produces: report only.
    hooks = lemmas | bad_bases
    review = sorted(
        w for w, r in acc.items()
        if r.get("base") in hooks and w not in forms and w not in INVALID and w not in FIX_BASE
    )

    print(f"verbs with forms of 2-9 letters: {len(lemmas)}; generated forms: {len(forms)}")
    print(f"add: {len(add)}  unblock: {len(unblock)} (+{len(extra)} other verbs)  "
          f"relabel: {len(relabel) + len(fix_base)}  remove: {len(remove)}  review only: {len(review)}")
    if args.dry_run:
        print("\n## add\n" + "\n".join(f"{w} — {describe(w, h)}" for w, h in add))
        print("\n## unblock\n" + "\n".join(f"{w} — {describe(w, h)}" for w, h in unblock))
        print("\n## unblock (other verbs)\n" + "\n".join(f"{w} — {describe(w, h)}" for w, h in extra))
        print("\n## relabel\n" + "\n".join(f"{w}: {b} → {describe(w, h)}" for w, b, h in relabel))
        print("\n".join(f"{w}: {acc[w].get('base')} → {d}" for w, l, d in fix_base))
        print("\n## remove\n" + "\n".join(f"{w} — {why}" for w, l, why in remove))
        print("\n## review only\n" + "\n".join(f"{w} ({acc[w].get('base')}): {acc[w].get('description')}" for w in review))
        return

    def entry(form: str, hits: list[tuple[str, str]], old: dict | None = None) -> dict:
        if old:
            row = dict(old)
        else:
            row = {"word": form, "description": None, "base": None,
                   "source": "morphology", "verified_by": "rule:sehen-saeen"}
        row["description"] = describe(form, hits)
        row["base"] = None if form in lemmas else hits[0][0]
        return row

    for form, hits in add:
        insert_sorted(accepted, entry(form, hits))
    for form, hits in unblock + extra:
        insert_sorted(accepted, entry(form, hits, rej.get(form) or unc.get(form)))
    gone = {w for w, _ in unblock + extra}
    rejected = [r for r in rejected if r["word"] not in gone]
    uncertain = [r for r in uncertain if r["word"] not in gone]
    for form, _, hits in relabel:
        acc[form]["description"] = describe(form, hits)
        acc[form]["base"] = hits[0][0]
    for form, lemma, desc in fix_base:
        acc[form]["description"], acc[form]["base"] = desc, lemma
    for form, lemma, why in remove:
        row = dict(acc[form])
        row["description"], row["base"] = why, lemma
        accepted = [r for r in accepted if r["word"] != form]
        insert_sorted(rejected, row)

    dump(ACCEPTED, accepted)
    dump(UNCERTAIN, uncertain)
    dump(REJECTED, rejected)
    print(f"accepted: {len(acc)} -> {len(accepted)}; rejected: {len(rej)} -> {len(rejected)}; "
          f"uncertain: {len(unc)} -> {len(uncertain)}")


if __name__ == "__main__":
    main()
