#!/usr/bin/env python3
"""Stop a paired benchmark when spend is unknown or reaches its cap."""

import json
from pathlib import Path
import sys


def measured_cost(directory):
    total = 0.0
    missing = []
    for path in sorted(Path(directory).glob("*.meta.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            value = record.get("metrics", {}).get("cost_usd")
            total += float(value)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
            missing.append(path.name)
    return total, missing


def main():
    if len(sys.argv) != 3:
        print("usage: budget.py <metadata-dir> <maximum-total-cost-usd>", file=sys.stderr)
        return 2
    try:
        cap = float(sys.argv[2])
    except ValueError:
        print("error: cost cap must be numeric", file=sys.stderr)
        return 2
    if cap <= 0:
        print("error: cost cap must be positive", file=sys.stderr)
        return 2
    total, missing = measured_cost(sys.argv[1])
    print(f"measured total cost: ${total:.4f} / ${cap:.4f}")
    if missing:
        print("budget stop: missing cost in " + ", ".join(missing), file=sys.stderr)
        return 4
    if total >= cap:
        print("budget stop: cap reached", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
