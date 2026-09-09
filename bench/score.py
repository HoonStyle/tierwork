#!/usr/bin/env python3
"""Score reported bug locations against a deterministic answer key.

Answer-key records use ``ID|path:start-end`` (the end is optional). A
location match is only evidence that the report points at the right place;
the scorer deliberately leaves semantic correctness for human review.
"""
import argparse
import json
import re

REF_RE = re.compile(r"(?P<path>[A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+):(?P<start>\d+)(?:-(?P<end>\d+))?")
KEY_RE = re.compile(r"^\s*(?P<id>[A-Za-z0-9_.-]+)\|\s*(?P<path>[A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+):(?P<start>\d+)(?:-(?P<end>\d+))?")


def normalize_path(path):
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def extract_ref_occurrences(text):
    """Return every reported reference, retaining duplicates and ranges."""
    return [
        {"path": normalize_path(match.group("path")),
         "start": int(match.group("start")),
         "end": int(match.group("end") or match.group("start")),
         "text": match.group(0)}
        for match in REF_RE.finditer(text or "")
    ]


def extract_refs(text):
    """Backward-compatible set of (path, start_line) references."""
    return {(ref["path"], ref["start"]) for ref in extract_ref_occurrences(text)}


def parse_answer_key(text):
    """Parse deterministic ``ID|path:range`` records from answer-key text."""
    entries = []
    for line_number, line in enumerate((text or "").splitlines(), 1):
        match = KEY_RE.match(line)
        if not match:
            continue
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if end < start:
            raise ValueError(f"answer key line {line_number}: range ends before it starts")
        entries.append({"id": match.group("id"), "path": normalize_path(match.group("path")),
                        "start": start, "end": end, "source_line": line_number})
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("answer key contains duplicate defect IDs")
    return entries


def load_result_text(result_json_path):
    with open(result_json_path, encoding="utf-8") as handle:
        data = json.load(handle)
    for key in ("result", "output", "text", "final_result"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return json.dumps(data)


def load_key_text(answer_key_path):
    with open(answer_key_path, encoding="utf-8") as handle:
        return handle.read()


def _location_classification(ref, entry):
    overlaps = ref["end"] >= entry["start"] and ref["start"] <= entry["end"]
    if ref["path"] != entry["path"] or not overlaps:
        return None
    if ref["start"] == entry["start"] and ref["end"] == entry["end"]:
        return "exact"
    if entry["start"] == entry["end"] and ref["start"] == entry["start"]:
        return "exact"
    return "range"


def score_text(result_text, key_text):
    entries = parse_answer_key(key_text)
    refs = extract_ref_occurrences(result_text)
    matches_by_entry = {entry["id"]: [] for entry in entries}
    ref_matches = []
    for index, ref in enumerate(refs):
        matches = [(entry, _location_classification(ref, entry)) for entry in entries]
        matches = [(entry, kind) for entry, kind in matches if kind]
        if not matches:
            classification = "outside"
        elif len(matches) > 1:
            classification = "ambiguous"
            for entry, _ in matches:
                matches_by_entry[entry["id"]].append((index, "ambiguous"))
        else:
            entry, classification = matches[0]
            matches_by_entry[entry["id"]].append((index, classification))
        ref_matches.append({"reference": ref, "classification": classification,
                            "candidate_answer_ids": [entry["id"] for entry, _ in matches],
                            "location_candidate": classification in {"exact", "range", "ambiguous"},
                            "semantic_review_required": classification in {"exact", "range", "ambiguous"}})

    answer_results = []
    for entry in entries:
        candidates = matches_by_entry[entry["id"]]
        kinds = {kind for _, kind in candidates}
        if not candidates:
            status = "missed"
        elif "ambiguous" in kinds:
            status = "ambiguous"
        elif len(candidates) > 1:
            status = "duplicate"
        else:
            status = candidates[0][1]
        answer_results.append({"id": entry["id"], "path": entry["path"], "start": entry["start"],
                               "end": entry["end"], "classification": status,
                               "reference_indexes": [index for index, _ in candidates],
                               "location_candidate": status in {"exact", "range", "duplicate", "ambiguous"},
                               "semantic_review_required": status in {"exact", "range", "duplicate", "ambiguous"}})

    counts = {kind: 0 for kind in ("exact", "range", "outside", "duplicate", "ambiguous", "missed")}
    for item in answer_results:
        counts[item["classification"]] += 1
    counts["outside_references"] = sum(item["classification"] == "outside" for item in ref_matches)
    matched_answers = sum(
        item["classification"] in {"exact", "range", "duplicate"}
        for item in answer_results
    )
    precision_denominator = matched_answers + counts["outside_references"]
    return {
        "answer_entries": answer_results,
        "references": ref_matches,
        "counts": counts,
        "location_recall": matched_answers / len(entries) if entries else None,
        "location_precision_candidate": (
            matched_answers / precision_denominator if precision_denominator else None
        ),
        "semantic_review_required": any(
            item["semantic_review_required"] for item in answer_results
        ),
        "semantic_review_complete": False,
        "authority": "location_candidates_only",
    }


def apply_judgments(report, judgments):
    """Attach an independent per-reference semantic review to a report."""
    if not isinstance(judgments, dict):
        raise ValueError("judgments must be a JSON object")
    reviewer = judgments.get("reviewer")
    independent = judgments.get("independent") is True
    supplied = judgments.get("references")
    if not isinstance(supplied, list):
        raise ValueError("judgments.references must be an array")
    by_index = {}
    for item in supplied:
        if not isinstance(item, dict) or not isinstance(item.get("index"), int):
            raise ValueError("every judgment needs an integer reference index")
        index = item["index"]
        if index in by_index or index < 0 or index >= len(report["references"]):
            raise ValueError(f"invalid or duplicate judgment index: {index}")
        verdict = item.get("verdict")
        if verdict not in {"true_positive", "false_positive", "unknown"}:
            raise ValueError(f"invalid semantic verdict at reference {index}")
        answer_id = item.get("answer_id")
        candidates = report["references"][index]["candidate_answer_ids"]
        if verdict == "true_positive" and answer_id not in candidates:
            raise ValueError(
                f"true_positive reference {index} must name one of {candidates}"
            )
        by_index[index] = {
            "verdict": verdict,
            "answer_id": answer_id if verdict == "true_positive" else None,
            "note": item.get("note"),
        }

    for index, reference in enumerate(report["references"]):
        reference["semantic_judgment"] = by_index.get(index)
    complete = (
        independent
        and isinstance(reviewer, str)
        and bool(reviewer.strip())
        and len(by_index) == len(report["references"])
        and all(item["verdict"] != "unknown" for item in by_index.values())
    )
    true_answer_ids = {
        item["answer_id"] for item in by_index.values()
        if item["verdict"] == "true_positive"
    }
    false_count = sum(
        item["verdict"] == "false_positive" for item in by_index.values()
    )
    precision_denominator = len(true_answer_ids) + false_count
    report["semantic_review"] = {
        "reviewer": reviewer,
        "independent": independent,
        "reference_judgments": len(by_index),
    }
    report["semantic_review_complete"] = complete
    report["semantic_recall"] = (
        len(true_answer_ids) / len(report["answer_entries"])
        if report["answer_entries"] else None
    )
    report["semantic_precision"] = (
        len(true_answer_ids) / precision_denominator
        if precision_denominator else None
    )
    report["authority"] = "independent_semantic_review" if complete else "partial_semantic_review"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_json")
    parser.add_argument("answer_key")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable JSON")
    parser.add_argument("--judgments", help="independent per-reference semantic judgments JSON")
    args = parser.parse_args()
    report = score_text(load_result_text(args.result_json), load_key_text(args.answer_key))
    if args.judgments:
        with open(args.judgments, encoding="utf-8") as handle:
            report = apply_judgments(report, json.load(handle))
    report["result"] = args.result_json
    report["answer_key"] = args.answer_key
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print("=== bench/score.py report ===")
    print(f"result:      {args.result_json}")
    print(f"answer_key:  {args.answer_key}")
    for entry in report["answer_entries"]:
        print(f"  [{entry['classification'].upper()}] {entry['id']} {entry['path']}:{entry['start']}-{entry['end']}")
    print("classification counts: " + ", ".join(f"{key}={value}" for key, value in report["counts"].items()))
    print("semantic review required: " + ("yes" if report["semantic_review_required"] else "no"))


if __name__ == "__main__":
    main()
