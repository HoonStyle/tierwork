#!/usr/bin/env bash
# SubagentStop hook: appends one JSON line per finished tierwork:* sub-agent
# to a local log for later aggregation by bench/report.py.
#
# Never blocks the session: always exits 0, never writes to stdout.
# Documented hook input fields (code.claude.com/docs/en/hooks): session_id,
# transcript_path, cwd, hook_event_name; in sub-agent context also agent_id,
# agent_type. All are treated as possibly missing.
#
# This is a thin launcher: the transcript-parsing logic lives in
# hooks/log-subagent.py (stdlib-only Python 3), used whenever a python3 (or,
# on Windows Git Bash, python) interpreter is available. If no Python is
# found, it falls back to a jq implementation. If neither python nor jq is
# available, it appends a minimal record so the log still gets created.
#
# Codex sub-agent runs (runtime: "codex") are only recognized by the Python
# path (log-subagent.py). The jq/minimal fallbacks below only ever emit
# runtime: "claude" records -- if python3 isn't available, Codex runs will
# not appear tagged in the dashboard (they will simply not match the
# tierwork:* Claude agent_type filter and be skipped).

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=find-python.sh
. "$DIR/find-python.sh"

# jq-based "running" record for SubagentStart (fallback when python is
# unavailable). Does not wait for/poll any transcript.
run_jq_start() {
  local input="$1"

  command -v jq >/dev/null 2>&1 || return 0

  local agent_type
  agent_type="$(printf '%s' "$input" | jq -r '.agent_type // empty' 2>/dev/null)" || return 0
  [ -n "$agent_type" ] || return 0

  case "$agent_type" in
    tierwork:*) ;;
    *) return 0 ;;
  esac

  local session_id agent_id transcript_path cwd
  session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
  agent_id="$(printf '%s' "$input" | jq -r '.agent_id // empty' 2>/dev/null)"
  transcript_path="$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null)"
  cwd="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)"

  # Best-effort sibling meta.json lookup, same derived path as SubagentStop.
  local description=""
  if [ -n "$transcript_path" ] && [ -n "$session_id" ] && [ -n "$agent_id" ]; then
    local main_dir candidate meta_path
    main_dir="$(dirname "$transcript_path" 2>/dev/null)"
    if [ -n "$main_dir" ]; then
      candidate="$main_dir/$session_id/subagents/agent-$agent_id.jsonl"
      meta_path="${candidate%.jsonl}.meta.json"
      [ -f "$meta_path" ] && description="$(jq -r '.description // empty' "$meta_path" 2>/dev/null)"
    fi
  fi

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"

  local log_path="${TIERWORK_LOG:-$HOME/.tierwork/reviews.jsonl}"
  mkdir -p "$(dirname "$log_path")" 2>/dev/null || return 0

  jq -nc \
    --arg ts "$ts" \
    --arg session_id "$session_id" \
    --arg agent_id "$agent_id" \
    --arg agent_type "$agent_type" \
    --arg description "$description" \
    --arg cwd "$cwd" \
    '{
      ts: $ts,
      session_id: ($session_id // null),
      agent_id: ($agent_id // null),
      agent_type: $agent_type,
      status: "running",
      description: (if $description == "" then null else $description end),
      cwd: (if $cwd == "" then null else $cwd end),
      runtime: "claude"
    }' >> "$log_path" 2>/dev/null

  return 0
}

# jq-based implementation (fallback when python is unavailable).
run_jq() {
  local input="$1"

  command -v jq >/dev/null 2>&1 || return 0

  local agent_type
  agent_type="$(printf '%s' "$input" | jq -r '.agent_type // empty' 2>/dev/null)" || return 0
  [ -n "$agent_type" ] || return 0

  case "$agent_type" in
    tierwork:*) ;;
    *) return 0 ;;
  esac

  local session_id agent_id transcript_path cwd
  session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
  agent_id="$(printf '%s' "$input" | jq -r '.agent_id // empty' 2>/dev/null)"
  transcript_path="$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null)"
  cwd="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)"

  # Locate the sub-agent transcript. Prefer the derived per-agent path when
  # it can be computed and exists: transcript_path in the hook input is
  # documented to point at the *main* session transcript, which itself can
  # contain "isSidechain":true / "agentId" markers (from the Task tool call
  # that spawned this sub-agent), so checking transcript_path first would
  # misidentify the main transcript as the sub-agent's own.
  local agent_transcript="" subagents_dir="" meta_path=""
  if [ -n "$transcript_path" ] && [ -n "$session_id" ] && [ -n "$agent_id" ]; then
    local main_dir
    main_dir="$(dirname "$transcript_path" 2>/dev/null)"
    if [ -n "$main_dir" ]; then
      subagents_dir="$main_dir/$session_id/subagents"
      local candidate="$subagents_dir/agent-$agent_id.jsonl"
      [ -f "$candidate" ] && agent_transcript="$candidate"
    fi
  fi

  if [ -z "$agent_transcript" ] && [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    if grep -q '"isSidechain":true' "$transcript_path" 2>/dev/null \
      || grep -q '"agentId"' "$transcript_path" 2>/dev/null; then
      agent_transcript="$transcript_path"
    fi
  fi

  [ -n "$agent_transcript" ] && [ -f "$agent_transcript" ] || agent_transcript=""

  # Sibling meta file for spawn model / description.
  local spawn_model="" description=""
  if [ -n "$agent_transcript" ]; then
    meta_path="${agent_transcript%.jsonl}.meta.json"
    if [ -f "$meta_path" ]; then
      spawn_model="$(jq -r '.model // empty' "$meta_path" 2>/dev/null)"
      description="$(jq -r '.description // empty' "$meta_path" 2>/dev/null)"
    fi
  fi

  # SubagentStop can fire before the sub-agent's final text record is flushed
  # (observed: hook at .16s, last record at .38s). Wait briefly until the last
  # assistant record carries a text block, up to ~2s.
  if [ -n "$agent_transcript" ]; then
    local tries=0
    while [ $tries -lt 5 ]; do
      if jq -s '[.[] | select(.type=="assistant")] | last | .message.content? | select(type=="array") | map(select(.type=="text")) | length > 0' "$agent_transcript" 2>/dev/null | grep -q true; then
        break
      fi
      sleep 0.4; tries=$((tries+1))
    done
  fi

  # Aggregate transcript stats with jq. All defaulted so a malformed or
  # missing transcript still produces a valid (mostly empty) record.
  local stats
  if [ -n "$agent_transcript" ]; then
    stats="$(jq -s '
      {
        models: ([.[] | select(.message.model != null) | .message.model] | unique),
        msgs: ([.[] | select(.type=="assistant")] | length),
        input_tokens: ([.[] | .message.usage.input_tokens? // 0] | add // 0),
        output_tokens: ([.[] | .message.usage.output_tokens? // 0] | add // 0),
        cache_read: ([.[] | .message.usage.cache_read_input_tokens? // 0] | add // 0),
        cache_create: ([.[] | .message.usage.cache_creation_input_tokens? // 0] | add // 0),
        tool_calls: ([.[] | .message.content? | select(type=="array") | .[] | select(.type=="tool_use")] | length),
        last_text: ([.[] | select(.type=="assistant") | .message.content? | select(type=="array") | .[] | select(.type=="text") | .text] | last // "")
      }
    ' "$agent_transcript" 2>/dev/null)"
  fi
  [ -n "${stats:-}" ] || stats='{"models":[],"msgs":0,"input_tokens":0,"output_tokens":0,"cache_read":0,"cache_create":0,"tool_calls":0,"last_text":""}'

  local last_text
  last_text="$(printf '%s' "$stats" | jq -r '.last_text // ""' 2>/dev/null)"
  last_text="${last_text:0:2000}"

  # Parse verdict/confidence/needs_primary_review/proceed from last_text,
  # case-insensitive, first match each.
  local verdict confidence needs_primary_review proceed
  verdict="$(printf '%s\n' "$last_text" | grep -io 'verdict:[[:space:]]*[^[:space:]]*' | head -1 | sed -E 's/^[Vv]erdict:[[:space:]]*//')"
  confidence="$(printf '%s\n' "$last_text" | grep -io 'confidence:[[:space:]]*[^[:space:]]*' | head -1 | sed -E 's/^[Cc]onfidence:[[:space:]]*//')"
  needs_primary_review="$(printf '%s\n' "$last_text" | grep -io 'needs_primary_review:[[:space:]]*[^[:space:]]*' | head -1 | sed -E 's/^[Nn]eeds_primary_review:[[:space:]]*//')"
  proceed="$(printf '%s\n' "$last_text" | grep -io 'proceed:[[:space:]]*[^[:space:]]*' | head -1 | sed -E 's/^[Pp]roceed:[[:space:]]*//')"

  # Strip any trailing punctuation left over from prose (e.g. "confirmed.").
  verdict="$(printf '%s' "$verdict" | sed -E 's/[.,;:]+$//')"
  confidence="$(printf '%s' "$confidence" | sed -E 's/[.,;:]+$//')"
  needs_primary_review="$(printf '%s' "$needs_primary_review" | sed -E 's/[.,;:]+$//')"
  proceed="$(printf '%s' "$proceed" | sed -E 's/[.,;:]+$//')"

  [ -n "$verdict" ] || verdict=""
  [ -n "$confidence" ] || confidence=""
  [ -n "$needs_primary_review" ] || needs_primary_review=""
  [ -n "$proceed" ] || proceed=""

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"

  local log_path="${TIERWORK_LOG:-$HOME/.tierwork/reviews.jsonl}"
  mkdir -p "$(dirname "$log_path")" 2>/dev/null || return 0

  jq -nc \
    --arg ts "$ts" \
    --arg session_id "$session_id" \
    --arg agent_id "$agent_id" \
    --arg agent_type "$agent_type" \
    --arg spawn_model "$spawn_model" \
    --argjson models "$(printf '%s' "$stats" | jq -c '.models // []')" \
    --argjson msgs "$(printf '%s' "$stats" | jq -c '.msgs // 0')" \
    --argjson tool_calls "$(printf '%s' "$stats" | jq -c '.tool_calls // 0')" \
    --argjson input_tokens "$(printf '%s' "$stats" | jq -c '.input_tokens // 0')" \
    --argjson output_tokens "$(printf '%s' "$stats" | jq -c '.output_tokens // 0')" \
    --argjson cache_read "$(printf '%s' "$stats" | jq -c '.cache_read // 0')" \
    --argjson cache_create "$(printf '%s' "$stats" | jq -c '.cache_create // 0')" \
    --arg verdict "$verdict" \
    --arg confidence "$confidence" \
    --arg needs_primary_review "$needs_primary_review" \
    --arg proceed "$proceed" \
    --arg cwd "$cwd" \
    --arg description "$description" \
    '{
      ts: $ts,
      session_id: ($session_id // null),
      agent_id: ($agent_id // null),
      agent_type: $agent_type,
      status: "done",
      spawn_model: (if $spawn_model == "" then null else $spawn_model end),
      models: $models,
      msgs: $msgs,
      tool_calls: $tool_calls,
      input_tokens: $input_tokens,
      output_tokens: $output_tokens,
      cache_read: $cache_read,
      cache_create: $cache_create,
      verdict: (if $verdict == "" then null else $verdict end),
      confidence: (if $confidence == "" then null else $confidence end),
      needs_primary_review: (if $needs_primary_review == "" then null else $needs_primary_review end),
      proceed: (if $proceed == "" then null else $proceed end),
      cwd: (if $cwd == "" then null else $cwd end),
      description: (if $description == "" then null else $description end),
      runtime: "claude"
    }' >> "$log_path" 2>/dev/null

  return 0
}

# Minimal fallback (no jq, no python) for SubagentStart: emit a single-line
# "running" record with plain grep/sed extraction. No transcript/meta.json
# lookup here -- description is omitted (left out of the object) in this path.
run_minimal_start() {
  local input="$1"

  local agent_type session_id agent_id
  agent_type="$(printf '%s' "$input" | grep -o '"agent_type"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"
  [ -n "$agent_type" ] || return 0
  case "$agent_type" in
    tierwork:*) ;;
    *) return 0 ;;
  esac

  session_id="$(printf '%s' "$input" | grep -o '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"
  agent_id="$(printf '%s' "$input" | grep -o '"agent_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"

  json_escape() {
    local val="$1"
    val="${val//\\/\\\\}"
    val="${val//\"/\\\"}"
    val="${val//$'\n'/\\n}"
    printf '%s' "$val"
  }

  local ts_e session_id_e agent_id_e agent_type_e
  ts_e="$(json_escape "$ts")"
  session_id_e="$(json_escape "$session_id")"
  agent_id_e="$(json_escape "$agent_id")"
  agent_type_e="$(json_escape "$agent_type")"

  local log_path="${TIERWORK_LOG:-$HOME/.tierwork/reviews.jsonl}"
  mkdir -p "$(dirname "$log_path")" 2>/dev/null || return 0

  printf '{"ts":"%s","session_id":"%s","agent_id":"%s","agent_type":"%s","status":"running","runtime":"claude"}\n' \
    "$ts_e" "$session_id_e" "$agent_id_e" "$agent_type_e" >> "$log_path" 2>/dev/null

  return 0
}

# Minimal fallback when neither python nor jq is available: emit a bare
# record (built with printf, no JSON tooling) so the log file still gets
# created and the miss is visible.
run_minimal() {
  local input="$1"

  # Extract agent_type / session_id / agent_id with plain sed/grep (best
  # effort; no jq available). Bail out quietly if we can't find agent_type
  # or it isn't a tierwork:* agent.
  local agent_type session_id agent_id
  agent_type="$(printf '%s' "$input" | grep -o '"agent_type"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"
  [ -n "$agent_type" ] || return 0
  case "$agent_type" in
    tierwork:*) ;;
    *) return 0 ;;
  esac

  session_id="$(printf '%s' "$input" | grep -o '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"
  agent_id="$(printf '%s' "$input" | grep -o '"agent_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"

  # Escape backslashes, double quotes, and newlines for safe embedding in a
  # JSON string literal built by hand.
  # Pure-bash escaping (no sed/awk/tr needed here): backslashes, double
  # quotes, and literal newlines, in that order.
  json_escape() {
    local val="$1"
    val="${val//\\/\\\\}"
    val="${val//\"/\\\"}"
    val="${val//$'\n'/\\n}"
    printf '%s' "$val"
  }

  local ts_e session_id_e agent_id_e agent_type_e
  ts_e="$(json_escape "$ts")"
  session_id_e="$(json_escape "$session_id")"
  agent_id_e="$(json_escape "$agent_id")"
  agent_type_e="$(json_escape "$agent_type")"

  local log_path="${TIERWORK_LOG:-$HOME/.tierwork/reviews.jsonl}"
  mkdir -p "$(dirname "$log_path")" 2>/dev/null || return 0

  printf '{"ts":"%s","session_id":"%s","agent_id":"%s","agent_type":"%s","status":"done","missing_tool":"python3+jq","runtime":"claude"}\n' \
    "$ts_e" "$session_id_e" "$agent_id_e" "$agent_type_e" >> "$log_path" 2>/dev/null

  return 0
}

main() {
  local input
  input="$(cat)" || return 0
  # Debug aid: TIERWORK_DEBUG_STDIN=<file> appends the raw hook input there.
  [ -n "${TIERWORK_DEBUG_STDIN:-}" ] && printf '%s\n' "$input" >> "$TIERWORK_DEBUG_STDIN" 2>/dev/null

  local py
  if py="$(find_python)"; then
    # shellcheck disable=SC2086  # $py may be "py -3"; intentionally unquoted
    printf '%s' "$input" | $py "$DIR/log-subagent.py" >/dev/null 2>&1
    return 0
  fi

  # No python available: the jq/minimal fallbacks below don't get python's
  # internal hook_event_name dispatch, so branch on it here ourselves.
  local hook_event_name=""
  if command -v jq >/dev/null 2>&1; then
    hook_event_name="$(printf '%s' "$input" | jq -r '.hook_event_name // empty' 2>/dev/null)"
  else
    hook_event_name="$(printf '%s' "$input" | grep -o '"hook_event_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"
  fi

  case "$hook_event_name" in
    SubagentStart)
      if command -v jq >/dev/null 2>&1; then
        run_jq_start "$input"
      else
        run_minimal_start "$input"
      fi
      return 0
      ;;
    SubagentStop)
      if command -v jq >/dev/null 2>&1; then
        run_jq "$input"
      else
        run_minimal "$input"
      fi
      return 0
      ;;
    *)
      return 0
      ;;
  esac
}

main "$@" 2>/dev/null
exit 0
