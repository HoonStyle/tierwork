#!/usr/bin/env python3
"""One-shot diagnostic view of Tierwork's recorded sub-agent status.

This is recorded hook state, not authoritative process liveness or proof that a
parent collected/integrated a result. It never starts, waits for, or cancels an
agent.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dashboard  # noqa: E402
from recorded_state import latest_recorded, parse_ts, recorded_status  # noqa: E402


def read_rows(paths):
    rows = []
    diagnostics = {"files": 0, "missingFiles": 0, "unreadableFiles": 0, "malformedLines": 0, "nonObjectLines": 0}
    for path in dashboard.resolve_log_files(paths):
        diagnostics["files"] += 1
        if not path.exists():
            diagnostics["missingFiles"] += 1
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        diagnostics["malformedLines"] += 1
                        continue
                    if not isinstance(row, dict):
                        diagnostics["nonObjectLines"] += 1
                        continue
                    row = dict(row)
                    row["source"] = path.name
                    rows.append(row)
        except (OSError, UnicodeError):
            diagnostics["unreadableFiles"] += 1
    return rows, diagnostics


def compact(row):
    return {
        "sessionId": row.get("session_id"),
        "agentId": row.get("agent_id"),
        "agentType": row.get("agent_type") or "unknown",
        "runtime": row.get("runtime") or "unknown",
        "recordedStatus": recorded_status(row),
        "recordedAt": row.get("ts"),
        "description": row.get("description"),
        "source": row.get("source"),
    }


def build_status(rows, diagnostics, *, session=None, agent=None, recent_seconds=300, now_value=None):
    deduped, skipped = latest_recorded(rows)
    if session:
        deduped = [row for row in deduped if row.get("session_id") == session]
    if agent:
        deduped = [row for row in deduped if row.get("agent_id") == agent]
    current = now_value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    running, completed, unknown = [], [], []
    for row in deduped:
        status = recorded_status(row)
        item = compact(row)
        if status == "running":
            running.append(item)
        elif status == "done":
            age = (current - parse_ts(row.get("ts"))).total_seconds()
            if 0 <= age <= recent_seconds:
                completed.append(item)
        else:
            unknown.append(item)
    key = lambda item: (item["recordedAt"], item["sessionId"], item["agentId"])
    return {
        "authority": "recorded_hook_status_only",
        "limitations": [
            "Not authoritative process liveness.",
            "done does not prove success, result retrieval, or parent integration.",
            "Assignment generation is unavailable; resumed agent IDs may be ambiguous.",
            "Missing hook records are inconclusive, especially when Codex hook trust is absent.",
        ],
        "filters": {"sessionId": session, "agentId": agent, "recentSeconds": recent_seconds},
        "inFlight": sorted(running, key=key, reverse=True),
        "recentlyCompleted": sorted(completed, key=key, reverse=True),
        "unknownStatus": sorted(unknown, key=key, reverse=True),
        "diagnostics": {**diagnostics, **skipped, "validLatestAssignments": len(deduped)},
    }


def render_text(payload):
    lines = [
        "Tierwork recorded status (diagnostic only; not process liveness)",
        f"in flight: {len(payload['inFlight'])} · recently completed: {len(payload['recentlyCompleted'])} · unknown: {len(payload['unknownStatus'])}",
    ]
    for heading, key in (("IN FLIGHT", "inFlight"), ("RECENTLY COMPLETED", "recentlyCompleted"), ("UNKNOWN STATUS", "unknownStatus")):
        if not payload[key]:
            continue
        lines.append(f"\n{heading}")
        for item in payload[key]:
            lines.append(f"- {item['runtime']} {item['agentType']} session={item['sessionId']} agent={item['agentId']} at={item['recordedAt']}")
    diag = payload["diagnostics"]
    lines.append(f"\nSkipped: identity={diag['invalidIdentity']} timestamp={diag['invalidTimestamp']} malformed={diag['malformedLines']} unreadable={diag['unreadableFiles']} missing={diag['missingFiles']}")
    lines.append("A done record triggers harness-native result retrieval; it is not proof the result was collected.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="append", dest="logs", help="JSONL file or directory; repeatable")
    parser.add_argument("--session")
    parser.add_argument("--agent")
    parser.add_argument("--recent-seconds", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.recent_seconds < 0:
        parser.error("--recent-seconds must be non-negative")
    paths = args.logs or [dashboard.default_log_path()]
    rows, diagnostics = read_rows(paths)
    payload = build_status(rows, diagnostics, session=args.session, agent=args.agent, recent_seconds=args.recent_seconds)
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else render_text(payload))
    return 1 if diagnostics["unreadableFiles"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
