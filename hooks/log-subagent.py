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


# ---------------------------------------------------------------------------
# Codex support
#
# Source: https://learn.chatgpt.com/docs/hooks (Codex Hooks docs, fetched
# 2026-09-04; developers.openai.com/codex/hooks 308-redirects there).
# Quoted fields actually used below:
#   "All events receive these common fields: session_id, cwd,
#    hook_event_name, transcript_path, and model."
#   "SubagentStart additionally receives: turn_id, agent_id, agent_type,
#    permission_mode"
#   "SubagentStop additionally receives: turn_id, agent_id, agent_type,
#    agent_transcript_path, stop_hook_active, last_assistant_message"
# Detection is NOT documented anywhere (no CODEX_* env var is mentioned in
# the hooks doc). We detect Codex by the presence of `agent_transcript_path`
# (SubagentStop) -- a key Claude's hook input never sends -- or, for
# SubagentStart, by the presence of a top-level `model` field, which Claude's
# hook input also never sends (Claude only puts `model` inside transcript
# records, never in the hook stdin JSON). This heuristic is UNVERIFIED
# against a real Codex hook firing (no Codex credits at implementation
# time); only the offline rollout-parsing path below was exercised against
# real ~/.codex/sessions/**/rollout-*.jsonl files.
def is_codex_input(data):
    # Codex's hooks doc lists "model" as a field common to ALL hook events
    # (SessionStart, SubagentStart, SubagentStop, Stop, ...). Claude's hook
    # input never has a top-level "model" key for any event -- Claude only
    # ever puts "model" inside transcript records, never in the hook stdin
    # JSON itself. That makes a top-level "model" key a reliable signal.
    # "agent_transcript_path" (Codex SubagentStop-only) is checked too as a
    # belt-and-braces second signal. transcript_path is NOT usable here: the
    # doc lists it as common to both runtimes' hook inputs.
    if "agent_transcript_path" in data:
        return True
    if "model" in data:
        return True
    return False


def read_rollout_jsonl(path):
    return read_jsonl(path)


def find_rollout_by_thread_id(agent_id):
    """Best-effort fallback when agent_transcript_path isn't in the hook
    input: scan ~/.codex/sessions/**/rollout-*.jsonl for a session_meta
    record whose payload.id matches agent_id, newest first. UNVERIFIED
    against live Codex hook firing; exercised only against real local
    rollout files."""
    if not agent_id:
        return ""
    root = os.path.join(os.path.expanduser("~"), ".codex", "sessions")
    if not os.path.isdir(root):
        return ""
    candidates = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.startswith("rollout-") and fn.endswith(".jsonl") and agent_id in fn:
                candidates.append(os.path.join(dirpath, fn))
    if not candidates:
        return ""
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def compute_codex_stats(records):
    """Aggregate a Codex rollout JSONL (list of {type, payload} dicts) into
    the same stat shape compute_stats() returns for Claude transcripts.

    Rollout schema (from real ~/.codex/sessions/**/rollout-*.jsonl files,
    read with jq; not from any written spec):
      - {"type":"session_meta","payload":{"id","session_id",
         "parent_thread_id","thread_source","source","cwd","timestamp"}}
      - {"type":"turn_context","payload":{"model",...}}
      - {"type":"response_item","payload":{"type":"message","role":
         "assistant"|"user"|"developer","content":[{"type":"output_text",
         "text":...}]}} (also "reasoning", "custom_tool_call",
         "custom_tool_call_output")
      - {"type":"token_usage_record","payload":{"thread_id","turn_id",
         "usage":{...},"turn_token_usage":{...},"thread_token_usage":
         {"input_tokens","cached_input_tokens","cache_write_input_tokens",
         "output_tokens","reasoning_output_tokens","total_tokens"}}}
      - {"type":"event_msg","payload":{"type":"task_complete",
         "last_assistant_message":...}} (also "task_started",
         "item_completed", "token_count")
    thread_token_usage is assumed cumulative-per-thread (its name implies
    this; only ever observed with a single turn in sampled files, so this
    could not be confirmed against a multi-turn thread). We therefore take
    the LAST token_usage_record's thread_token_usage as the run total
    rather than summing every record (summing would double-count if
    thread_token_usage is already cumulative). UNVERIFIED assumption.
    """
    models = []
    msgs = 0
    tool_calls = 0
    last_text = ""
    last_usage = None

    for rec in records:
        if not isinstance(rec, dict):
            continue
        rtype = rec.get("type")
        payload = rec.get("payload")
        if not isinstance(payload, dict):
            continue

        if rtype == "turn_context":
            model = payload.get("model")
            if model and model not in models:
                models.append(model)

        elif rtype == "response_item":
            ptype = payload.get("type")
            if ptype == "message" and payload.get("role") == "assistant":
                msgs += 1
                content = payload.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "output_text":
                            last_text = block.get("text") or last_text
            elif ptype in ("custom_tool_call", "function_call", "local_shell_call"):
                tool_calls += 1

        elif rtype == "token_usage_record":
            usage = payload.get("thread_token_usage")
            if isinstance(usage, dict):
                last_usage = usage

        elif rtype == "event_msg":
            if payload.get("type") == "task_complete":
                msg = payload.get("last_assistant_message")
                if msg:
                    last_text = msg

    if last_usage is None:
        last_usage = {}

    return {
        "models": models,
        "msgs": msgs,
        "input_tokens": last_usage.get("input_tokens") or 0,
        "output_tokens": last_usage.get("output_tokens") or 0,
        "cache_read": last_usage.get("cached_input_tokens") or 0,
        "cache_create": last_usage.get("cache_write_input_tokens") or 0,
        "tool_calls": tool_calls,
        "last_text": last_text,
    }


def codex_agent_label(data, rollout_path=None):
    """Codex sub-agents spawned via the collab tool arrive with agent_type
    "default" (observed live 2026-09-04), so the tierwork:* filter used for
    Claude cannot apply. Label = agent_role or agent_nickname from the
    sub-agent rollout's session_meta when readable, else the hook's
    agent_type; tierwork:* names pass through unchanged, everything else is
    prefixed "codex:" so the dashboard can tell the runtimes apart."""
    agent_type = data.get("agent_type") or "default"
    label = None
    if rollout_path and os.path.isfile(rollout_path):
        try:
            for rec in read_rollout_jsonl(rollout_path):
                if rec.get("type") != "session_meta":
                    continue
                src = (rec.get("payload") or {}).get("source") or {}
                spawn = (src.get("subagent") or {}).get("thread_spawn") or {} if isinstance(src, dict) else {}
                label = spawn.get("agent_role") or spawn.get("agent_nickname") or None
                if not label and spawn.get("agent_path"):
                    label = os.path.splitext(os.path.basename(spawn["agent_path"]))[0]
                break
        except Exception:
            label = None
    label = label or agent_type
    return label if label.startswith("tierwork:") else "codex:" + label


def handle_codex_subagent_start(data):
    agent_type = codex_agent_label(data)

    session_id = data.get("session_id") or ""
    agent_id = data.get("agent_id") or ""
    cwd = data.get("cwd") or ""

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
        "status": "running",
        "description": None,
        "cwd": cwd or None,
        "runtime": "codex",
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    except OSError:
        return 0
    return 0


def handle_codex_subagent_stop(data):
    agent_type = codex_agent_label(data, data.get("agent_transcript_path"))

    session_id = data.get("session_id") or ""
    agent_id = data.get("agent_id") or ""
    cwd = data.get("cwd") or ""
    spawn_model = data.get("model") or ""

    rollout_path = data.get("agent_transcript_path") or ""
    if not rollout_path or not os.path.isfile(rollout_path):
        rollout_path = find_rollout_by_thread_id(agent_id)

    records = []
    if rollout_path and os.path.isfile(rollout_path):
        records = read_rollout_jsonl(rollout_path)

    stats = compute_codex_stats(records) if records else {
        "models": [], "msgs": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_read": 0, "cache_create": 0, "tool_calls": 0, "last_text": "",
    }

    last_text = (data.get("last_assistant_message") or stats.get("last_text") or "")[:2000]

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
        "status": "done",
        "spawn_model": spawn_model or (stats.get("models") or [None])[0],
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
        "description": None,
        "runtime": "codex",
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    except OSError:
        return 0
    return 0


def handle_subagent_start(session_id, agent_id, agent_type, transcript_path, cwd):
    """Append a lightweight 'running' record for a just-spawned tierwork
    sub-agent. Never waits for/polls the transcript and never computes
    token stats -- SubagentStop's record later supersedes this one."""
    description = None
    try:
        if transcript_path and session_id and agent_id:
            main_dir = os.path.dirname(transcript_path)
            if main_dir:
                candidate = os.path.join(
                    main_dir, session_id, "subagents", "agent-%s.jsonl" % agent_id
                )
                meta_path = re.sub(r"\.jsonl$", ".meta.json", candidate)
                if os.path.isfile(meta_path):
                    with open(meta_path, "r", encoding="utf-8", errors="replace") as f:
                        meta = json.load(f)
                    if isinstance(meta, dict):
                        description = meta.get("description") or None
    except Exception:
        description = None

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
        "status": "running",
        "description": description,
        "cwd": cwd or None,
        "runtime": "claude",
    }

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    except OSError:
        return 0

    return 0


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

    hook_event_name = data.get("hook_event_name") or ""

    if is_codex_input(data):
        if hook_event_name == "SubagentStart":
            return handle_codex_subagent_start(data)
        if hook_event_name == "SubagentStop":
            return handle_codex_subagent_stop(data)
        return 0

    agent_type = data.get("agent_type") or ""
    if not agent_type or not agent_type.startswith("tierwork:"):
        return 0

    session_id = data.get("session_id") or ""
    agent_id = data.get("agent_id") or ""
    transcript_path = data.get("transcript_path") or ""
    cwd = data.get("cwd") or ""

    if hook_event_name == "SubagentStart":
        return handle_subagent_start(
            session_id, agent_id, agent_type, transcript_path, cwd
        )

    if hook_event_name != "SubagentStop":
        return 0

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
        "status": "done",
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
        "runtime": "claude",
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
