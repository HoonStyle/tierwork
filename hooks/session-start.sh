#!/usr/bin/env bash
# Prints the tierwork delegation policy to stdout as plain text, followed by
# a one-line summary of the local review log if it exists.
# Both Claude Code and Codex CLI add SessionStart stdout as context.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${TIERWORK_LOG:-$HOME/.tierwork/reviews.jsonl}"

cat "$DIR/policy.md"

# shellcheck source=find-python.sh
. "$DIR/find-python.sh"

if [ -s "$LOG" ]; then
  SUMMARY=""
  PY="$(find_python)"
  if [ -n "$PY" ]; then
    # shellcheck disable=SC2086  # $PY may be "py -3"; intentionally unquoted
    SUMMARY=$($PY - "$LOG" <<'PYEOF' 2>/dev/null
import json, sys

log_path = sys.argv[1]
records = []
try:
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(rec, dict) and rec.get("agent_type") is not None:
                records.append(rec)
except OSError:
    records = []

n = len(records)
if n == 0:
    sys.exit(0)

validators = [r for r in records if r.get("agent_type") == "tierwork:bug-validator"]
confirmed = len([r for r in validators if r.get("verdict") == "confirmed"])
needs_review = len([r for r in validators if r.get("needs_primary_review") == "yes"])
out_tokens = sum(r.get("output_tokens") or 0 for r in records)

print(
    "Tierwork log: %d sub-agent runs, validators %d (confirmed %d, needs_primary_review %d), "
    "output tokens %d. Report: bench/report.py"
    % (n, len(validators), confirmed, needs_review, out_tokens)
)
PYEOF
)
  elif command -v jq >/dev/null 2>&1; then
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
  fi
  [ -n "$SUMMARY" ] && printf '\n%s\n' "$SUMMARY"
fi

exit 0
