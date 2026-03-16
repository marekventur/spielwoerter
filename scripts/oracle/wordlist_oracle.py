#!/usr/bin/env python3
"""
wordlist-oracle.py — Multi-language Scrabble word list oracle

Checks a candidate Scrabble word list (from stdin) against the authoritative
tournament dictionary for a given language. Dictionaries are from the
[Scrabble3D Dictionaries](https://github.com/Scrabble3D/Dictionaries) project.

This oracle is built to safely verify the quality of a candidate word list against
an authoritative reference list for a given language, even if the license of
the reference list is not permissive. To achieve that, this script ensures that
no information about individual words in the authoritative reference list
is returned and that only aggregated metrics are reported.

Dictionary files are not included in this repo (copyright of their authors).
They are downloaded automatically on first use for the chosen language.

Usage:
    cat my_wordlist.txt | python wordlist_oracle.py [--language LANG] [--fraction N] [--nonce STRING]
    cat my_wordlist.txt | python wordlist_oracle.py --filter-fraction [--fraction N] [--nonce STRING]

Options:
    --language LANG   Language dictionary to use (default: deutsch). See supported list below.
    --fraction N      Include only 1/N of words (by hash). Default: 1 (all words).
                      Applied identically to both the reference and candidate list,
                      so relative scores remain valid for smaller test runs.
    --return-mismatches  Include false positives and false negatives (word lists) in JSON output.
                         Only valid when --fraction is used (fraction != 1).
    --nonce STRING    Salt for the hash used in fraction sampling. Default: "".
    --filter-fraction Run as a filter only: read words from stdin, apply the same
                      fraction/nonce logic, and print kept words to stdout (one per line).
                      No dictionary is loaded; use this to build a fractional test set
                      compatible with the oracle without reimplementing the sampling logic.

Supported languages (use as --language value):
    brazilian, catalan, deutsch, english, english_phonetic, espanol, francais,
    greek, hebrew, hollands, hungarian, irish, italiano, latin, persian, polish,
    portuguese, romana, russian, scottishgaelic, slovak, suomi, svenska, tamil, turkish

Output: In normal mode, JSON to stdout. With --filter-fraction, one word per line to stdout.
Progress and errors go to stderr.
"""

import sys
import os
import base64
import hashlib
import json
import argparse
import urllib.request
import zipfile
import io

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DIC_BASE_URL = 'https://github.com/Scrabble3D/Dictionaries/raw/main'

# All .dic.zip languages from https://github.com/Scrabble3D/Dictionaries
SUPPORTED_LANGUAGES = [
    'brazilian', 'catalan', 'deutsch', 'english', 'english_phonetic', 'espanol',
    'francais', 'greek', 'hebrew', 'hollands', 'hungarian', 'irish', 'italiano',
    'latin', 'persian', 'polish', 'portuguesa', 'romana', 'russian', 'scottishgaelic',
    'slovak', 'suomi', 'svenska', 'tamil', 'turkish',
]
KEY = b'7AVFU8PP'
MAX_HASH = 2 ** 256


def find_or_download_dic(language):
    """Return path to the dictionary file for the given language, downloading if necessary."""
    dic_zip = f'{language}.dic.zip'
    dic_file = f'{language}.dic'
    path = os.path.join(SCRIPT_DIR, dic_file)
    if os.path.exists(path):
        return path

    url = f'{DIC_BASE_URL}/{dic_zip}'
    print(f"Dictionary file not found. Downloading from:\n  {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(url) as response:
            zip_bytes = response.read()
    except Exception as e:
        print(f"ERROR: Download failed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            dic_names = [n for n in zf.namelist() if n.endswith('.dic')]
            if not dic_names:
                print("ERROR: No .dic file found in downloaded zip.", file=sys.stderr)
                sys.exit(1)
            dic_name = dic_names[0]
            print(f"Extracting {dic_name} -> {path}", file=sys.stderr)
            with zf.open(dic_name) as src, open(path, 'wb') as dst:
                dst.write(src.read())
    except Exception as e:
        print(f"ERROR: Extraction failed: {e}", file=sys.stderr)
        sys.exit(1)

    return path


def should_include(word, nonce, fraction):
    if fraction == 1:
        return True
    h = int(hashlib.sha256((nonce + word).encode('utf-8')).hexdigest(), 16)
    return h < MAX_HASH // fraction


def load_superdic(path, nonce, fraction):
    """Load reference words (2-9 letters) from a SuperDic .dic file."""
    data = open(path, 'rb').read()
    idx = data.find(b'[Words]\r\n')
    if idx == -1:
        print("ERROR: [Words] section not found in dictionary file.", file=sys.stderr)
        sys.exit(1)
    words_data = data[idx + len(b'[Words]\r\n'):]
    total = 0
    words = set()
    for line in words_data.split(b'\r\n'):
        if not line:
            continue
        decoded_bytes = bytes(b ^ KEY[i % len(KEY)] for i, b in enumerate(base64.b64decode(line)))
        decoded = decoded_bytes.decode('utf-8', errors='replace')
        eq_pos = decoded.index('=')
        word = decoded[:eq_pos]
        rest = decoded[eq_pos + 1:]
        if ';1' in rest or ';2' in rest:
            continue  # Extended/graded entries only; skip for base list
        if 2 <= len(word) <= 9:
            total += 1
            if should_include(word, nonce, fraction):
                words.add(word)
    return total, words


def load_candidate(stream, nonce, fraction):
    """Load candidate words (2-9 letters) from a newline-separated stream."""
    total = 0
    words = set()
    for line in stream:
        word = line.strip().upper()
        if not word or not (2 <= len(word) <= 9):
            continue
        total += 1
        if should_include(word, nonce, fraction):
            words.add(word)
    return total, words


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--language', type=str, default='deutsch',
                        help=f'Dictionary language (default: deutsch). Choices: {", ".join(SUPPORTED_LANGUAGES)}')
    parser.add_argument('--fraction', type=int, default=1,
                        help='Include 1/N of words by hash (default: 1 = all)')
    parser.add_argument('--return-mismatches', action='store_true',
                        help='Include false positives and false negatives in output (only valid with --fraction)')
    parser.add_argument('--nonce', type=str, default='',
                        help='Salt for hash-based sampling (default: empty string)')
    parser.add_argument('--filter-fraction', action='store_true',
                        help='Filter stdin by fraction/nonce and print kept words to stdout')
    args = parser.parse_args()

    if args.filter_fraction:
        for line in sys.stdin:
            word = line.strip().upper()
            if not word or not (2 <= len(word) <= 9):
                continue
            if should_include(word, args.nonce, args.fraction):
                print(word)
        return

    if args.language not in SUPPORTED_LANGUAGES:
        print(f"ERROR: Unsupported language '{args.language}'. Choose from: {', '.join(SUPPORTED_LANGUAGES)}", file=sys.stderr)
        sys.exit(1)

    dic_path = find_or_download_dic(args.language)

    print(f"Loading dictionary from {os.path.basename(dic_path)}...", file=sys.stderr, end=' ', flush=True)
    ref_total, ref = load_superdic(dic_path, args.nonce, args.fraction)
    print(f"{ref_total} words total, {len(ref)} sampled.", file=sys.stderr)

    print("Reading candidate words from stdin...", file=sys.stderr, end=' ', flush=True)
    candidate_total, candidate = load_candidate(sys.stdin, args.nonce, args.fraction)
    print(f"{candidate_total} words total, {len(candidate)} sampled.", file=sys.stderr)

    tp = len(candidate & ref)
    fp_set = candidate - ref
    fn_set = ref - candidate
    fp = len(fp_set)
    fn = len(fn_set)

    if args.return_mismatches:
        if args.fraction < 1000:
            print("ERROR: --return-mismatches is only valid when --fraction is less than 1000.", file=sys.stderr)
            sys.exit(1)

    result = {
        "language": args.language,
        "nonce": args.nonce,
        "fraction": args.fraction,
        "reference_total": ref_total,
        "reference_sampled": len(ref),
        "candidate_total": candidate_total,
        "candidate_sampled": len(candidate),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "recall_pct": round(tp / len(ref) * 100, 4) if ref else 0.0,
        "precision_pct": round(tp / len(candidate) * 100, 4) if candidate else 0.0,
    }
    if args.return_mismatches:
        result["false_positive_words"] = sorted(fp_set)
        result["false_negative_words"] = sorted(fn_set)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
