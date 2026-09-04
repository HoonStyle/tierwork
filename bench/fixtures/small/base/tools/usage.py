"""Aggregate token usage per model from Claude Code session jsonl files."""
import json, sys, pathlib, collections

def load(path):
    for line in pathlib.Path(path).read_text().splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue

def totals(root):
    acc = collections.defaultdict(lambda: collections.Counter())
    for f in pathlib.Path(root).rglob("*.jsonl"):
        for rec in load(f):
            msg = rec.get("message") or {}
            if rec.get("type") != "assistant" or "usage" not in msg:
                continue
            u = msg["usage"]
            acc[msg["model"]]["in"] += u.get("input_tokens", 0)
            acc[msg["model"]]["out"] += u.get("output_tokens", 0)
            acc[msg["model"]]["cache_read"] += u.get("cache_read_input_tokens", 0)
    return acc

if __name__ == "__main__":
    for model, c in sorted(totals(sys.argv[1]).items()):
        print(model, dict(c))
