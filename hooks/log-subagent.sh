#!/usr/bin/env bash
# SubagentStop hook: appends one JSON line per finished tierwork:* sub-agent
# to a local log for later aggregation by bench/report.py.
#
# Never blocks the session: always exits 0, never writes to stdout.
# Documented hook input fields (code.claude.com/docs/en/hooks): session_id,
# transcript_path, cwd, hook_event_name; in sub-agent context also agent_id,
# agent_type. All are treated as possibly missing.

set -u

main() {
  local input
  input="$(cat)" || return 0

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
      description: (if $description == "" then null else $description end)
    }' >> "$log_path" 2>/dev/null

  return 0
}

main "$@" 2>/dev/null
exit 0
