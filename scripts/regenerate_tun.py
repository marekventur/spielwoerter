"""
One-off data fix (2026-09): rebuild the forms of the verbs on -tun.

"tun" is irregular, so the website's rule-based conjugator refuses every verb
ending in it and their forms came from the LLM pass: many are missing (tuen,
tuet, tätst, antut, austust ...) and some that were accepted are not German
(tunendem, tuntet, antung). Reported by moderator Panikpilz, who supplied the
full paradigm of tun including e-Tilgung and the 43 compounds with their
separability (scripts/data/verben_tun.txt).

The stem of tun never changes after a prefix, so every form is prefix + a fixed
ending. The script derives them by rule (REGELN.md, "Verben") and compares them
with the three lists, exactly like
scripts/regenerate_sehen_saeen.py:

  add       form is in no list                         -> accepted
  unblock   form is in rejected or uncertain           -> accepted
  relabel   form is accepted under a wrong base        -> base/description fixed
  remove    accepted "form" of these verbs that is not German -> rejected

There is no length limit: the moderators decided in 2026-10 that the list is not
bound to Scrabble's 9 letters (Wortopia plays up to 25).

Not generated: joined imperatives of separable verbs ("auftu" is generated, but
as 1st person singular) and comparatives of participles. The declined Partizip
II and the Gerundiv ("abzutuende", only with an adjective ending, only for
separable verbs since "zu vertuende" is two words) only for transitive verbs
(TRANSITIVE). nottun only has the forms in RESTRICTED.

Usage:
    python3 scripts/regenerate_tun.py            # rewrite the lists
    python3 scripts/regenerate_tun.py --dry-run  # only print the report
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

MIN_LEN = 2
ADJ = ("e", "em", "en", "er", "es")

# Partizip II may only be declined, and the Gerundiv only formed, for transitive
# verbs (REGELN.md). umtun and vortun as in "eine Schürze umtun/vortun"; betun
# confirmed by the moderators ("sein betanes Verhalten"). Not here: intransitive
# wehtun, guttun, mittun, großtun, leidtun ..., reflexive sich übertun,
# sich leichttun, and "es jemandem gleichtun/zuvortun/nachtun".
TRANSITIVE = {
    "tun", "abtun", "antun", "auftun", "austun", "betun", "dartun", "dazutun", "durchtun",
    "heraustun", "hinauftun", "hinaustun", "hineintun", "hintun", "hinübertun", "hinzutun",
    "kundtun", "reintun", "umtun", "vertun", "vortun", "wegtun", "wiedertun", "zurücktun",
    "zusammentun", "zutun",
}

# Verbs with a restricted paradigm, as supplied by the moderators: only these
# forms exist, every other accepted form of the verb is removed.
RESTRICTED = {
    "nottun": {
        "nottun": "Infinitiv sowie 1./3. Person Plural Präsens",
        "nottu": "1./3. Person Singular Konjunktiv I (mit e-Tilgung)",
        "nottue": "1./3. Person Singular Konjunktiv I",
        "nottuen": "1./3. Person Plural Konjunktiv I",
        "nottat": "1./3. Person Singular Präteritum",
        "nottaten": "1./3. Person Plural Präteritum",
        "nottät": "1./3. Person Singular Konjunktiv II (mit e-Tilgung)",
        "nottäte": "1./3. Person Singular Konjunktiv II",
        "nottäten": "1./3. Person Plural Konjunktiv II",
        "notzutun": "Infinitiv mit zu",
        "notzutuend": "Gerundiv",
        "notzutuende": "Gerundiv, dekliniert",
        "notzutuendem": "Gerundiv, dekliniert",
        "notzutuenden": "Gerundiv, dekliniert",
        "notzutuender": "Gerundiv, dekliniert",
        "notzutuendes": "Gerundiv, dekliniert",
        "nottuns": "Genitiv des substantivierten Infinitivs",
    },
}

# Deviations from the supplied list. genugtun is marked "nein" there, but it
# splits like the other adverb compounds (tat genug, genuggetan), and treating
# it as inseparable would add the non-word "genugtan".
SEPARABLE_OVERRIDE = {"genugtun": True}

# Lemmas from the supplied list that are not in the list yet need a real description.
LEMMA_DESCRIPTIONS = {
    "durchtun": "Verb — (umgangssprachlich) durch etwas hindurchbringen, z. B. durch ein Sieb",
    "hinaustun": "Verb — (umgangssprachlich) nach draußen bringen, hinausstellen",
    "leichttun": "Verb — sich leichttun: keine Mühe mit etwas haben",
    "wiedertun": "Verb — noch einmal tun, wiederholen",
    "zuvortun": "Verb — es jemandem zuvortun: jemanden übertreffen",
    "übeltun": "Verb — (veraltend) Böses tun, Unrecht tun",
    "übertun": "Verb — sich übertun: sich übernehmen, zu viel tun",
    "heimlichtun": "Verb — geheimnisvoll tun, Geheimnisse haben",
    "hinübertun": "Verb — (umgangssprachlich) auf die andere Seite bringen",
    "zusammentun": "Verb — zusammenlegen; sich zusammentun: sich verbünden",
    "reintun": "Verb — (umgangssprachlich) hineintun",
    "rumtun": "Verb — (umgangssprachlich) herumtun",
    "weitertun": "Verb — weitermachen, fortfahren",
    "zugutetun": "Verb — sich etwas zugutetun: sich etwas gönnen",
    "nottun": "Verb — (gehoben) nötig sein, not tun",
    "antun": "Verb — jemandem etwas (Böses) zufügen; sich etwas antun",
    "nachtun": "Verb — es jemandem nachtun: nachahmen, gleichtun",
    "schöntun": "Verb — schmeicheln, sich einschmeicheln",
    "vortun": "Verb — (umgangssprachlich) vorbinden, z. B. eine Schürze",
}

# Accepted entries filed under these verbs that are not forms of anything.
# (tunendem, tuntet and tutest look similar but are forms of tunen and tuten.)
INVALID = {
    "antung": ("antun", "Keine Form von antun (Präteritum: antat)."),
    "tuenda": ("tun", "Keine Form von tun (Partizip I: tuend, tuende)."),
    "nachtest": ("nachtun", "Keine Form von nachtun (Präteritum: nachtatest, nachtatst)."),
    "nachteste": ("nachtun", "Keine Form von nachtun (Konjunktiv II: nachtäte)."),
    "genugten": ("genugtun", "Keine Form von genugtun (Präteritum: genugtaten)."),
    # Pre-1901 spellings, not in any current dictionary (confirmed by the moderators).
    "abgethan": ("abtun", "Veraltete Schreibung (vor 1901) von abgetan, nicht mehr gültig."),
    "zuthat": ("zutun", "Veraltete Schreibung (vor 1901) von zutat, nicht mehr gültig."),
    "aufthun": (None, "Veraltete Schreibung (vor 1901) von auftun, nicht mehr gültig."),
    "wohlthun": (None, "Veraltete Schreibung (vor 1901) von wohltun, nicht mehr gültig."),
    "wohlthut": ("wohlthun", "Veraltete Schreibung (vor 1901) von wohltut, nicht mehr gültig."),
    "zugethan": ("zugetan", "Veraltete Schreibung (vor 1901) von zugetan, nicht mehr gültig."),
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


def tun_forms(lemma: str, separable: bool) -> Forms:
    p = lemma[: -len("tun")]
    f = Forms()
    f.put(p + "tun", "Infinitiv sowie 1./3. Person Plural Präsens")
    f.put(p + "tue", "1. Person Singular Präsens sowie 1./3. Person Singular Konjunktiv I")
    f.put(p + "tu", "1. Person Singular Präsens (mit e-Tilgung)")
    f.put(p + "tust", "2. Person Singular Präsens")
    f.put(p + "tut", "3. Person Singular und 2. Person Plural Präsens")
    f.put(p + "tuest", "2. Person Singular Konjunktiv I")
    f.put(p + "tuen", "1./3. Person Plural Konjunktiv I")
    f.put(p + "tuet", "2. Person Plural Konjunktiv I")
    f.put(p + "tat", "1./3. Person Singular Präteritum")
    f.put(p + "tatest", "2. Person Singular Präteritum")
    f.put(p + "tatst", "2. Person Singular Präteritum")
    f.put(p + "taten", "1./3. Person Plural Präteritum")
    f.put(p + "tatet", "2. Person Plural Präteritum")
    f.put(p + "täte", "1./3. Person Singular Konjunktiv II")
    f.put(p + "tät", "1./3. Person Singular Konjunktiv II (mit e-Tilgung)")
    f.put(p + "tätest", "2. Person Singular Konjunktiv II")
    f.put(p + "tätst", "2. Person Singular Konjunktiv II")
    f.put(p + "täten", "1./3. Person Plural Konjunktiv II")
    f.put(p + "tätet", "2. Person Plural Konjunktiv II")
    f.put(p + "tuns", "Genitiv des substantivierten Infinitivs")
    f.put(p + "tuend", "Partizip I")
    for e in ADJ:
        f.put(p + "tuend" + e, "Partizip I, dekliniert")
    if not separable:
        f.put(p + "tu", "Imperativ Singular")
        f.put(p + "tue", "Imperativ Singular")
    if separable:
        f.put(p + "zutun", "Infinitiv mit zu")
        if lemma in TRANSITIVE:
            for e in ADJ:
                f.put(p + "zutuend" + e, "Gerundiv, dekliniert")
    pii = p + ("ge" if (separable or p == "") else "") + "tan"
    f.put(pii, "Partizip II")
    if lemma in TRANSITIVE:
        for e in ADJ:
            f.put(pii + e, "Partizip II, dekliniert")
    return f


def paradigm() -> dict[str, list[tuple[str, str]]]:
    """form -> [(lemma, description fragment)], every lemma that yields it."""
    verbs = [("tun", False)] + read_verbs(DATA / "verben_tun.txt")
    out: dict[str, list[tuple[str, str]]] = {}
    for lemma, sep in verbs:
        sep = SEPARABLE_OVERRIDE.get(lemma, sep)
        forms = RESTRICTED.get(lemma) or tun_forms(lemma, sep)
        for form, desc in forms.items():
            if len(form) < MIN_LEN:
                continue
            out.setdefault(form, []).append((lemma, desc))
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
    return "; ".join(f"{desc} von {lemma}" for lemma, desc in hits)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    accepted, uncertain, rejected = load(ACCEPTED), load(UNCERTAIN), load(REJECTED)
    acc = {r["word"]: r for r in accepted}
    unc = {r["word"]: r for r in uncertain}
    rej = {r["word"]: r for r in rejected}
    forms = paradigm()
    lemmas = {l for hits in forms.values() for l, _ in hits}
    # Lemmas not in the list yet get the plain Infinitiv description; the ones
    # already there keep their dictionary-style description.
    new_lemmas = sorted(l for l in lemmas if l not in acc)

    add, unblock, relabel = [], [], []
    for form, hits in sorted(forms.items()):
        ok_bases = {l for l, _ in hits}
        if form in acc:
            base = acc[form].get("base")
            # Lemmas and words with a sense of their own (base None) keep their entry.
            if base is None or base in ok_bases or form in lemmas:
                continue
            # Filed under another tun-verb, or under a non-lemma form.
            if base in lemmas or base not in acc or acc[base].get("base") is not None:
                relabel.append((form, base, hits))
        elif form in rej or form in unc:
            unblock.append((form, hits))
        else:
            add.append((form, hits))
    remove = [(w, l, why) for w, (l, why) in INVALID.items() if w in acc and acc[w].get("base") == l]
    remove += [
        (w, r["base"], f"Keine gebräuchliche Form von {r['base']} (nur: {', '.join(RESTRICTED[r['base']])}).")
        for w, r in sorted(acc.items())
        if r.get("base") in RESTRICTED and w not in forms
    ]
    # Lemma entries filed under one of their own forms ("nottun" under "notgetan").
    lemma_fix = [w for w in sorted(lemmas) if w in acc and acc[w].get("base") is not None
                 and (acc[w]["base"] not in acc or acc[acc[w]["base"]].get("base") is not None)]

    # Accepted entries that hang off these verbs but that no rule produces: report only.
    review = sorted(
        w for w, r in acc.items()
        if r.get("base") in lemmas and w not in forms and w not in INVALID
        and r.get("base") not in RESTRICTED
    )

    print(f"verbs: {len(lemmas)} (new lemmas: {', '.join(new_lemmas)}); generated forms: {len(forms)}")
    print(f"add: {len(add)}  unblock: {len(unblock)}  relabel: {len(relabel)}  "
          f"remove: {len(remove)}  lemma base fixed: {len(lemma_fix)}  review only: {len(review)}")
    if args.dry_run:
        print("\n## add\n" + "\n".join(f"{w} — {describe(w, h)}" for w, h in add))
        print("\n## unblock\n" + "\n".join(
            f"{w} — {describe(w, h)}  [was: {(rej.get(w) or unc.get(w)).get('description')}]" for w, h in unblock))
        print("\n## relabel\n" + "\n".join(f"{w}: {b} → {describe(w, h)}" for w, b, h in relabel))
        print("\n## remove\n" + "\n".join(f"{w} — {why}" for w, l, why in remove))
        print("\n## lemma base fixed\n" + "\n".join(f"{w}: {acc[w]['base']} → (Stichwort)" for w in lemma_fix))
        print("\n## review only\n" + "\n".join(
            f"{w} ({acc[w].get('base')}): {acc[w].get('description')}" for w in review))
        return

    def entry(form: str, hits: list[tuple[str, str]], old: dict | None = None) -> dict:
        if old:
            row = dict(old)
        else:
            row = {"word": form, "description": None, "base": None,
                   "source": "morphology", "verified_by": "rule:tun"}
        row["description"] = LEMMA_DESCRIPTIONS.get(form) or describe(form, hits)
        row["base"] = None if form in lemmas else hits[0][0]
        return row

    for form, hits in add:
        insert_sorted(accepted, entry(form, hits))
    for form, hits in unblock:
        insert_sorted(accepted, entry(form, hits, rej.get(form) or unc.get(form)))
    gone = {w for w, _ in unblock}
    rejected = [r for r in rejected if r["word"] not in gone]
    uncertain = [r for r in uncertain if r["word"] not in gone]
    for form, _, hits in relabel:
        acc[form]["description"] = describe(form, hits)
        acc[form]["base"] = hits[0][0]
    for form in lemma_fix:
        acc[form]["base"] = None
        acc[form]["description"] = LEMMA_DESCRIPTIONS.get(form) or acc[form].get("description")
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
