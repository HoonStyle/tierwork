#!/usr/bin/env python3
"""Aggregate paired benchmark metadata without hiding failed condition runs."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summary(values):
    values = [number(value) for value in values]
    values = [value for value in values if value is not None]
    if not values:
        return {"n": 0, "mean": None, "median": None, "stdev": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else None,
    }


def location_recall(record):
    score = record.get("score")
    if not isinstance(score, dict):
        return None
    value = score.get("location_recall")
    if value is None and isinstance(score.get("summary"), dict):
        value = score["summary"].get("location_recall")
    return number(value)


def semantic_recall(record):
    score = record.get("score")
    if not isinstance(score, dict) or score.get("semantic_review_complete") is not True:
        return None
    return number(score.get("semantic_recall"))


def semantic_precision(record):
    score = record.get("score")
    if not isinstance(score, dict) or score.get("semantic_review_complete") is not True:
        return None
    return number(score.get("semantic_precision"))


def semantic_complete(record):
    score = record.get("score")
    return isinstance(score, dict) and score.get("semantic_review_complete") is True


def aggregate_cohort(records, config):
    pairs = defaultdict(dict)
    incomplete = []
    for record in records:
        if record.get("status") != "completed":
            incomplete.append({
                "run_id": record.get("run_id"),
                "condition": record.get("condition"),
                "status": record.get("status") or "unknown",
            })
            continue
        condition = record.get("condition")
        if condition not in {"disabled", "enabled"}:
            incomplete.append({
                "run_id": record.get("run_id"),
                "condition": condition,
                "status": "out_of_pair_contract",
            })
            continue
        pairs[record.get("pair_id")][condition] = record

    complete_pairs = []
    for pair_id, conditions in pairs.items():
        if set(conditions) == {"disabled", "enabled"}:
            complete_pairs.append((pair_id, conditions["disabled"], conditions["enabled"]))
        else:
            for record in conditions.values():
                incomplete.append({
                    "run_id": record.get("run_id"),
                    "condition": record.get("condition"),
                    "status": "unpaired",
                })

    conditions_summary = {}
    for condition, index in (("disabled", 1), ("enabled", 2)):
        selected = [pair[index] for pair in complete_pairs]
        conditions_summary[condition] = {
            "cost_usd": summary([row.get("metrics", {}).get("cost_usd") for row in selected]),
            "duration_ms": summary([row.get("metrics", {}).get("duration_ms") for row in selected]),
            "num_turns": summary([row.get("metrics", {}).get("num_turns") for row in selected]),
            "location_recall": summary([location_recall(row) for row in selected]),
            "semantic_recall": summary([semantic_recall(row) for row in selected]),
            "semantic_precision": summary([semantic_precision(row) for row in selected]),
        }

    cost_deltas = []
    recall_deltas = []
    precision_deltas = []
    for _pair_id, disabled, enabled in complete_pairs:
        disabled_cost = number(disabled.get("metrics", {}).get("cost_usd"))
        enabled_cost = number(enabled.get("metrics", {}).get("cost_usd"))
        if disabled_cost not in (None, 0) and enabled_cost is not None:
            cost_deltas.append((disabled_cost - enabled_cost) / disabled_cost)
        disabled_recall = semantic_recall(disabled)
        enabled_recall = semantic_recall(enabled)
        if disabled_recall is not None and enabled_recall is not None:
            recall_deltas.append(enabled_recall - disabled_recall)
        disabled_precision = semantic_precision(disabled)
        enabled_precision = semantic_precision(enabled)
        if disabled_precision is not None and enabled_precision is not None:
            precision_deltas.append(enabled_precision - disabled_precision)

    thresholds = {
        "minimum_pairs": config.get("minimum_pairs"),
        "recall_noninferiority_margin": config.get("recall_noninferiority_margin"),
        "precision_noninferiority_margin": config.get("precision_noninferiority_margin"),
        "minimum_cost_improvement_fraction": config.get("minimum_cost_improvement_fraction"),
        "maximum_total_cost_usd": config.get("maximum_total_cost_usd"),
    }
    conclusion = "inconclusive"
    reasons = []
    if any(value is None for value in thresholds.values()):
        reasons.append("claim thresholds were not preregistered")
    elif any(
        number(record.get("maximum_total_cost_usd"))
        != number(thresholds["maximum_total_cost_usd"])
        for record in records
    ):
        reasons.append("recorded cost cap does not match the preregistered config")
    elif len(complete_pairs) < int(thresholds["minimum_pairs"]):
        reasons.append("complete pair count is below the preregistered minimum")
    elif not all(semantic_complete(row) for pair in complete_pairs for row in pair[1:]):
        reasons.append("independent semantic review is incomplete")
    elif not cost_deltas or not recall_deltas or not precision_deltas:
        reasons.append("paired cost, recall, or precision metrics are missing")
    else:
        recall_ok = statistics.fmean(recall_deltas) >= -float(thresholds["recall_noninferiority_margin"])
        precision_ok = statistics.fmean(precision_deltas) >= -float(thresholds["precision_noninferiority_margin"])
        cost_ok = statistics.fmean(cost_deltas) >= float(thresholds["minimum_cost_improvement_fraction"])
        conclusion = "supported" if recall_ok and precision_ok and cost_ok else "not_supported"

    return {
        "complete_pairs": len(complete_pairs),
        "incomplete_runs": sorted(incomplete, key=lambda item: str(item.get("run_id"))),
        "conditions": conditions_summary,
        "paired_cost_improvement_fraction": summary(cost_deltas),
        "paired_semantic_recall_delta": summary(recall_deltas),
        "paired_semantic_precision_delta": summary(precision_deltas),
        "thresholds": thresholds,
        "conclusion": conclusion,
        "reasons": reasons,
    }


def aggregate(records, config):
    cohorts = defaultdict(list)
    for record in records:
        key = (
            record.get("experiment_id"), record.get("fixture"),
            record.get("main_model"), record.get("policy_revision"),
            record.get("maximum_total_cost_usd"),
        )
        cohorts[key].append(record)
    return {
        "schema_version": 1,
        "cohorts": [
            {
                "experiment_id": key[0], "fixture": key[1],
                "main_model": key[2], "policy_revision": key[3],
                "maximum_total_cost_usd": key[4],
                **aggregate_cohort(rows, config),
            }
            for key, rows in sorted(cohorts.items(), key=lambda item: tuple(str(v) for v in item[0]))
        ],
    }


def load_records(paths):
    files = []
    for value in paths:
        path = Path(value)
        files.extend(sorted(path.rglob("*.meta.json")) if path.is_dir() else [path])
    records = []
    for path in files:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict):
            score_path = Path(str(path)[:-len(".meta.json")] + ".score.json") if str(path).endswith(".meta.json") else None
            if score_path is not None and score_path.is_file():
                try:
                    current_score = json.loads(score_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    current_score = None
                if isinstance(current_score, dict):
                    value["score"] = current_score
            records.append(value)
    return records


def render_text(payload):
    lines = ["Tierwork paired benchmark aggregate"]
    for cohort in payload["cohorts"]:
        lines.append(
            f"\n{cohort['experiment_id']} fixture={cohort['fixture']} "
            f"model={cohort['main_model']} revision={cohort['policy_revision']}"
        )
        lines.append(
            f"complete pairs: {cohort['complete_pairs']} · "
            f"incomplete runs: {len(cohort['incomplete_runs'])}"
        )
        lines.append(f"conclusion: {cohort['conclusion']}")
        for reason in cohort["reasons"]:
            lines.append(f"- {reason}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="metadata files or directories")
    parser.add_argument("--config", required=True, help="preregistered claim thresholds JSON")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    payload = aggregate(load_records(args.paths), config)
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else render_text(payload))


if __name__ == "__main__":
    main()
