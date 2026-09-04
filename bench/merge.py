#!/usr/bin/env python3
"""Merge multiple tierwork review logs (files or directories of *.jsonl)
into one de-duped JSONL file, for combining data collected on different
machines.

Usage:
    bench/merge.py in1.jsonl [in2.jsonl|dir ...] -o merged.jsonl

Each input may be a single .jsonl file or a directory (globbed
non-recursively for *.jsonl, sorted for determinism). Rows are de-duplicated
by (session_id, agent_id), keeping the row with the latest `ts` (same rule
bench/dashboard.py uses for --log). Each row is tagged with a `source` field
set to the basename of the file it came from.

Stdlib only, no third-party deps. Does not start any server.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dashboard  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "inputs",
        nargs="+",
        help="one or more reviews.jsonl files or directories of *.jsonl files",
    )
    ap.add_argument("-o", "--output", required=True, help="path to write merged JSONL to")
    args = ap.parse_args()

    resolved_files = dashboard.resolve_log_files(args.inputs)
    all_rows = dashboard.load_jsonl_multi(args.inputs)
    merged = dashboard.dedup_rows(all_rows)

    out_path = os.path.expanduser(args.output)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for row in merged:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Input files: {len(resolved_files)}")
    print(f"Rows read: {len(all_rows)}")
    print(f"Rows written after de-dup: {len(merged)}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
