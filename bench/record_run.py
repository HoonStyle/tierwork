#!/usr/bin/env python3
"""Create a reproducible metadata envelope for one benchmark condition."""

import argparse
import hashlib
import json
from pathlib import Path


def load_object(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def build_metadata(args):
    raw = load_object(args.raw)
    score = load_object(args.score) if args.score_exit == 0 else None
    success = args.run_exit == 0 and raw is not None and score is not None
    status = "completed" if success else "interrupted" if args.run_exit in {130, 143} else "failed"
    metrics = {}
    if raw is not None:
        metrics = {
            "session_id": raw.get("session_id"),
            "cost_usd": raw.get("total_cost_usd", raw.get("cost_usd")),
            "duration_ms": raw.get("duration_ms"),
            "num_turns": raw.get("num_turns"),
            "model_usage": raw.get("model_usage", raw.get("usage")),
        }
    return {
        "schema_version": 1,
        "experiment_id": args.experiment,
        "run_id": f"{args.experiment}-{args.fixture}-r{args.repeat}-{args.condition}",
        "pair_id": f"{args.experiment}-{args.fixture}-r{args.repeat}",
        "fixture": args.fixture,
        "condition": args.condition,
        "repeat": args.repeat,
        "main_model": args.model,
        "policy_revision": args.policy_revision,
        "maximum_total_cost_usd": args.cost_cap,
        "started_at": args.started_at,
        "ended_at": args.ended_at,
        "status": status,
        "run_exit_code": args.run_exit,
        "score_exit_code": args.score_exit,
        "raw_result": Path(args.raw).name,
        "raw_result_sha256": sha256(args.raw),
        "metrics": metrics,
        "score": score,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--score", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--repeat", required=True, type=int)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--policy-revision", required=True)
    parser.add_argument("--cost-cap", type=float)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--ended-at", required=True)
    parser.add_argument("--run-exit", required=True, type=int)
    parser.add_argument("--score-exit", required=True, type=int)
    args = parser.parse_args()
    metadata = build_metadata(args)
    Path(args.output).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
