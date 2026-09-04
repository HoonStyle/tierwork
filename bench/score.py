#!/usr/bin/env python3
"""bench/score.py <result.json> <answer_key.md>

Compares path:line references found in a bench run's result JSON (the
`result` text field from `claude -p --output-format json`) against the
path:line references in a Markdown answer key, and reports found / missed /
extra.

Matching approach: exact match on (normalized_path, line_number). A
"path:line-line" range is reduced to its start line for matching. This is an
exact match, not fuzzy — no line-number tolerance is applied. Only the
basename-preserving relative path as written in the text is used (paths are
lightly normalized: leading "./" stripped, backslashes converted to "/").
"""
import argparse
import json
import re
import sys

# Matches things like "inv/tax.py:16", "tools/usage.py:22-24", "a/b/c.py:5"
REF_RE = re.compile(
    r'(?P<path>[A-Za-z0-9_./\-]+\.[A-Za-z0-9_]+):(?P<start>\d+)(?:-(?P<end>\d+))?'
)


def normalize_path(p: str) -> str:
    p = p.strip()
    p = p.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def extract_refs(text: str):
    refs = set()
    for m in REF_RE.finditer(text or ""):
        path = normalize_path(m.group("path"))
        line = int(m.group("start"))
        refs.add((path, line))
    return refs


def load_result_text(result_json_path: str) -> str:
    with open(result_json_path, "r") as f:
        data = json.load(f)
    # Prefer the documented `result` field; fall back to a couple of
    # plausible alternates if absent.
    for key in ("result", "output", "text", "final_result"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    # Last resort: stringify the whole payload so refs embedded elsewhere
    # are still found.
    return json.dumps(data)


def load_key_text(answer_key_path: str) -> str:
    with open(answer_key_path, "r") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("result_json", help="path to a claude -p --output-format json result file")
    ap.add_argument("answer_key", help="path to an ANSWER.md-style answer key file")
    args = ap.parse_args()

    result_text = load_result_text(args.result_json)
    key_text = load_key_text(args.answer_key)

    result_refs = extract_refs(result_text)
    key_refs = extract_refs(key_text)

    found = sorted(result_refs & key_refs)
    missed = sorted(key_refs - result_refs)
    extra = sorted(result_refs - key_refs)

    def fmt(refs):
        return [f"{p}:{l}" for p, l in refs] or ["(none)"]

    print("=== bench/score.py report ===")
    print(f"result:      {args.result_json}")
    print(f"answer_key:  {args.answer_key}")
    print()
    print(f"key refs found in result:   {len(found)}/{len(key_refs)}")
    for r in fmt(found):
        print(f"  [FOUND] {r}")
    print()
    print(f"key refs missed:             {len(missed)}")
    for r in fmt(missed):
        print(f"  [MISSED] {r}")
    print()
    print(f"extra refs (not in key):     {len(extra)}")
    for r in fmt(extra):
        print(f"  [EXTRA] {r}")
    print()
    if key_refs:
        recall = len(found) / len(key_refs)
        print(f"recall: {recall:.2f} ({len(found)}/{len(key_refs)})")
    else:
        print("recall: n/a (empty answer key)")


if __name__ == "__main__":
    main()
