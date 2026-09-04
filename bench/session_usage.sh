#!/bin/bash
# usage: bench/session_usage.sh <session_id>
#
# Given a session id from a `claude -p --output-format json` result, prints:
#   - per-sub-agent info (agentType, spawn model, actual models used)
#   - a per-model token-usage totals table across the main session jsonl and
#     all subagents/*.jsonl files
#   - any "gate agent" text lines matching the known gate-signal keys
#
# Structure verified against a real session
# (785e3ec2-0422-4725-a741-87d1925816e1) under ~/.claude/projects:
#   <project-dir>/<session_id>.jsonl              main session transcript
#   <project-dir>/<session_id>/subagents/agent-*.jsonl        per-subagent transcript
#   <project-dir>/<session_id>/subagents/agent-*.meta.json    per-subagent metadata
#     meta.json shape: {"agentType":..., "description":..., "toolUseId":...,
#                        "spawnDepth":..., "model":...}
# This matched the task description, so no adaptation was needed.
set -euo pipefail

SESSION_ID="${1:?usage: bench/session_usage.sh <session_id>}"

if ! command -v jq >/dev/null 2>&1; then
  echo "error: jq is required" >&2
  exit 1
fi

MAIN_JSONL="$(find ~/.claude/projects -name "${SESSION_ID}.jsonl" -not -path "*/subagents/*" 2>/dev/null | head -1)"

if [ -z "$MAIN_JSONL" ]; then
  echo "error: could not find ${SESSION_ID}.jsonl under ~/.claude/projects" >&2
  exit 1
fi

SESSION_DIR="${MAIN_JSONL%.jsonl}"
SUBAGENTS_DIR="$SESSION_DIR/subagents"

echo "main session jsonl: $MAIN_JSONL"
echo "session dir: $SESSION_DIR"
echo

echo "=== Sub-agents ==="
if [ -d "$SUBAGENTS_DIR" ]; then
  for meta in "$SUBAGENTS_DIR"/*.meta.json; do
    [ -e "$meta" ] || continue
    agent_jsonl="${meta%.meta.json}.jsonl"
    agent_type="$(jq -r '.agentType // "?"' "$meta")"
    spawn_model="$(jq -r '.model // "?"' "$meta")"
    description="$(jq -r '.description // ""' "$meta")"
    actual_models="unknown"
    if [ -f "$agent_jsonl" ]; then
      actual_models="$(jq -r 'select(.type=="assistant") | .message.model // empty' "$agent_jsonl" 2>/dev/null | sort -u | paste -sd, -)"
      [ -z "$actual_models" ] && actual_models="(none)"
    fi
    echo "agentType: $agent_type"
    echo "  description: $description"
    echo "  spawn_model: $spawn_model"
    echo "  actual_models_used: $actual_models"
    echo "  jsonl: $agent_jsonl"
    echo
  done
else
  echo "(no subagents/ directory found)"
  echo
fi

echo "=== Per-model token totals (main session + all subagents/*.jsonl) ==="
# Token-aggregation logic adapted from reference usage_by_model.sh.
{
  echo "$MAIN_JSONL"
  if [ -d "$SUBAGENTS_DIR" ]; then
    find "$SUBAGENTS_DIR" -name '*.jsonl'
  fi
} | xargs -I{} jq -c '
    select(.type=="assistant" and .message.usage != null) |
    {
      model: .message.model,
      input: (.message.usage.input_tokens // 0),
      output: (.message.usage.output_tokens // 0),
      cache_read: (.message.usage.cache_read_input_tokens // 0),
      cache_creation: (.message.usage.cache_creation_input_tokens // 0)
    }
  ' {} 2>/dev/null \
  | jq -s '
      group_by(.model) | map({
        model: .[0].model,
        messages: length,
        input_tokens: (map(.input) | add),
        output_tokens: (map(.output) | add),
        cache_read_tokens: (map(.cache_read) | add),
        cache_creation_tokens: (map(.cache_creation) | add)
      })
    ' \
  | jq -r '
      (["MODEL","MESSAGES","INPUT","OUTPUT","CACHE_READ","CACHE_CREATE"] | @tsv),
      (.[] | [.model, .messages, .input_tokens, .output_tokens, .cache_read_tokens, .cache_creation_tokens] | @tsv)
    ' \
  | column -t -s $'\t'

echo
echo "=== Gate agent signals ==="
# Look for a subagent whose agentType looks like a gate/router, else grep
# across all subagent jsonl text content for the known signal keys.
GATE_FILES=""
if [ -d "$SUBAGENTS_DIR" ]; then
  for meta in "$SUBAGENTS_DIR"/*.meta.json; do
    [ -e "$meta" ] || continue
    agent_type="$(jq -r '.agentType // ""' "$meta")"
    if echo "$agent_type" | grep -qiE 'gate|router'; then
      GATE_FILES="$GATE_FILES ${meta%.meta.json}.jsonl"
    fi
  done
fi
if [ -z "$GATE_FILES" ] && [ -d "$SUBAGENTS_DIR" ]; then
  GATE_FILES="$(ls "$SUBAGENTS_DIR"/*.jsonl 2>/dev/null | tr '\n' ' ')"
fi

if [ -n "$GATE_FILES" ]; then
  grep -hoE '^(size|review_tier|validation_tier|changed_files|changed_lines|stake_signals):.*' $GATE_FILES 2>/dev/null | sort -u
  # Also check inside jsonl text fields where lines may be embedded/escaped.
  grep -hoE '"(size|review_tier|validation_tier|changed_files|changed_lines|stake_signals): [^"\\]*"' $GATE_FILES 2>/dev/null | sort -u
else
  echo "(no subagent files to search)"
fi
