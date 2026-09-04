#!/usr/bin/env bash
# Prints the tierwork delegation policy to stdout as plain text, followed by
# a one-line summary of the local review log if it exists.
# Both Claude Code and Codex CLI add SessionStart stdout as context.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${TIERWORK_LOG:-$HOME/.tierwork/reviews.jsonl}"

cat "$DIR/policy.md"

if [ -s "$LOG" ] && command -v jq >/dev/null 2>&1; then
  SUMMARY=$(jq -rs '
    map(select(.agent_type != null)) as $r
    | ($r | length) as $n
    | ($r | map(select(.agent_type == "tierwork:bug-validator"))) as $v
    | ($v | map(select(.verdict == "confirmed")) | length) as $c
    | ($v | map(select(.needs_primary_review == "yes")) | length) as $p
    | ($r | map(.output_tokens // 0) | add // 0) as $out
    | if $n == 0 then empty else
      "Tierwork log: \($n) sub-agent runs, validators \($v|length) (confirmed \($c), needs_primary_review \($p)), output tokens \($out). Report: bench/report.py"
      end' "$LOG" 2>/dev/null)
  [ -n "$SUMMARY" ] && printf '\n%s\n' "$SUMMARY"
fi

exit 0
