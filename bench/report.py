#!/usr/bin/env python3
"""Aggregate tierwork's SubagentStop review log.

Usage:
    bench/report.py [path]

`path` defaults to ~/.tierwork/reviews.jsonl (or $TIERWORK_LOG if set).
Reads a JSON-Lines file (one object per line, as written by
hooks/log-subagent.sh) and prints summary statistics. Stdlib only.
"""

import json
import os
import sys
from collections import Counter, defaultdict


def default_path():
    env = os.environ.get("TIERWORK_LOG")
    if env:
        return env
    return os.path.expanduser("~/.tierwork/reviews.jsonl")


def load_rows(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: skipping malformed line {line_no}", file=sys.stderr)
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def as_number(value, default=0):
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def mean(values):
    values = [v for v in values if v is not None]
    if not values:
        return 0.0
    return sum(values) / len(values)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else default_path()
    rows = load_rows(path)

    print(f"log path: {path}")
    print(f"total rows: {len(rows)}")

    if not rows:
        print("(no data)")
        return

    by_type = defaultdict(list)
    for r in rows:
        by_type[r.get("agent_type") or "(unknown)"].append(r)

    print()
    print("== per agent_type ==")
    for agent_type in sorted(by_type):
        group = by_type[agent_type]
        models = set()
        for r in group:
            m = r.get("models")
            if isinstance(m, list):
                models.update(m)
        out_tokens = sum(as_number(r.get("output_tokens")) for r in group)
        in_tokens = sum(
            as_number(r.get("input_tokens"))
            + as_number(r.get("cache_read"))
            + as_number(r.get("cache_create"))
            for r in group
        )
        mean_tools = mean([as_number(r.get("tool_calls")) for r in group])
        print(f"- {agent_type}")
        print(f"    count: {len(group)}")
        print(f"    distinct models: {sorted(models) if models else '(none)'}")
        print(f"    sum output tokens: {out_tokens:.0f}")
        print(f"    sum input+cache tokens: {in_tokens:.0f}")
        print(f"    mean tool_calls: {mean_tools:.2f}")

    validator_rows = [
        r for r in rows if (r.get("agent_type") or "") == "tierwork:bug-validator"
    ]
    if validator_rows:
        print()
        print("== bug-validator ==")
        verdicts = Counter(
            (r.get("verdict") or "(none)") for r in validator_rows
        )
        print(f"    rows: {len(validator_rows)}")
        print(f"    verdict distribution: {dict(verdicts)}")
        needs_review = sum(
            1
            for r in validator_rows
            if str(r.get("needs_primary_review") or "").strip().lower() == "yes"
        )
        share = needs_review / len(validator_rows) if validator_rows else 0.0
        print(f"    needs_primary_review=yes share: {share:.2%}")
        confidences = []
        for r in validator_rows:
            c = r.get("confidence")
            if c is None:
                continue
            try:
                confidences.append(float(c))
            except (TypeError, ValueError):
                continue
        if confidences:
            print(f"    mean confidence: {mean(confidences):.2f}")
        else:
            print("    mean confidence: (no numeric confidence values)")

    print()
    print("== per day ==")
    day_counts = Counter()
    for r in rows:
        ts = r.get("ts") or ""
        day = ts[:10] if len(ts) >= 10 else "(unknown)"
        day_counts[day] += 1
    for day in sorted(day_counts):
        print(f"    {day}: {day_counts[day]}")


if __name__ == "__main__":
    main()
