#!/usr/bin/env python3
"""SubagentStop hook (python3 fallback / preferred path): appends one JSON
line per finished tierwork:* sub-agent to a local log for later aggregation
by bench/report.py.

Mirrors hooks/log-subagent.sh's jq implementation exactly. stdlib only.
Never blocks the session: always exits 0, never writes to stdout.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone


def read_jsonl(path):
    records = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except (ValueError, TypeError):
                    continue
    except OSError:
        return []
    return records


def last_text_has_content(records):
    for rec in reversed(records):
        if not isinstance(rec, dict):
            continue
        if rec.get("type") != "assistant":
            continue
        message = rec.get("message")
        if not isinstance(message, dict):
            return False
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return True
            return False
        return False
    return False


def compute_stats(records):
    models = []
    msgs = 0
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_create = 0
    tool_calls = 0
    last_text = ""

    for rec in records:
        if not isinstance(rec, dict):
            continue
        message = rec.get("message")
        if isinstance(message, dict):
            model = message.get("model")
            if model is not None and model not in models:
                models.append(model)

        if rec.get("type") == "assistant":
            msgs += 1
            if isinstance(message, dict):
                usage = message.get("usage")
                if isinstance(usage, dict):
                    input_tokens += usage.get("input_tokens") or 0
                    output_tokens += usage.get("output_tokens") or 0
                    cache_read += usage.get("cache_read_input_tokens") or 0
                    cache_create += usage.get("cache_creation_input_tokens") or 0
                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "tool_use":
                                tool_calls += 1
                            if block.get("type") == "text":
                                last_text = block.get("text") or ""

    return {
        "models": models,
        "msgs": msgs,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read": cache_read,
        "cache_create": cache_create,
        "tool_calls": tool_calls,
        "last_text": last_text,
    }


def parse_field(text, field):
    m = re.search(r"(?i)" + field + r":\s*(\S*)", text)
    if not m:
        return ""
    val = m.group(1)
    val = re.sub(r"[.,;:]+$", "", val)
    return val


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    if not isinstance(data, dict):
        return 0

    agent_type = data.get("agent_type") or ""
    if not agent_type or not agent_type.startswith("tierwork:"):
        return 0

    session_id = data.get("session_id") or ""
    agent_id = data.get("agent_id") or ""
    transcript_path = data.get("transcript_path") or ""
    cwd = data.get("cwd") or ""

    agent_transcript = ""
    if transcript_path and session_id and agent_id:
        main_dir = os.path.dirname(transcript_path)
        if main_dir:
            candidate = os.path.join(
                main_dir, session_id, "subagents", "agent-%s.jsonl" % agent_id
            )
            if os.path.isfile(candidate):
                agent_transcript = candidate

    if not agent_transcript and transcript_path and os.path.isfile(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if '"isSidechain":true' in content or '"agentId"' in content:
                agent_transcript = transcript_path
        except OSError:
            pass

    if agent_transcript and not os.path.isfile(agent_transcript):
        agent_transcript = ""

    spawn_model = ""
    description = ""
    if agent_transcript:
        meta_path = re.sub(r"\.jsonl$", ".meta.json", agent_transcript)
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8", errors="replace") as f:
                    meta = json.load(f)
                if isinstance(meta, dict):
                    spawn_model = meta.get("model") or ""
                    description = meta.get("description") or ""
            except (ValueError, TypeError, OSError):
                pass

    records = []
    if agent_transcript:
        records = read_jsonl(agent_transcript)
        tries = 0
        while tries < 5:
            if last_text_has_content(records):
                break
            time.sleep(0.4)
            records = read_jsonl(agent_transcript)
            tries += 1

    if agent_transcript:
        stats = compute_stats(records)
    else:
        stats = {
            "models": [],
            "msgs": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read": 0,
            "cache_create": 0,
            "tool_calls": 0,
            "last_text": "",
        }

    last_text = (stats.get("last_text") or "")[:2000]

    verdict = parse_field(last_text, "verdict")
    confidence = parse_field(last_text, "confidence")
    needs_primary_review = parse_field(last_text, "needs_primary_review")
    proceed = parse_field(last_text, "proceed")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log_path = os.environ.get("TIERWORK_LOG") or os.path.join(
        os.path.expanduser("~"), ".tierwork", "reviews.jsonl"
    )
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
    except OSError:
        return 0

    record = {
        "ts": ts,
        "session_id": session_id or None,
        "agent_id": agent_id or None,
        "agent_type": agent_type,
        "spawn_model": spawn_model or None,
        "models": stats.get("models") or [],
        "msgs": stats.get("msgs") or 0,
        "tool_calls": stats.get("tool_calls") or 0,
        "input_tokens": stats.get("input_tokens") or 0,
        "output_tokens": stats.get("output_tokens") or 0,
        "cache_read": stats.get("cache_read") or 0,
        "cache_create": stats.get("cache_create") or 0,
        "verdict": verdict or None,
        "confidence": confidence or None,
        "needs_primary_review": needs_primary_review or None,
        "proceed": proceed or None,
        "cwd": cwd or None,
        "description": description or None,
    }

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    except OSError:
        return 0

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception:
        sys.exit(0)
