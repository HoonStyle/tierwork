#!/bin/bash
# usage: bench/run.sh <label> [fixture]
#
# Runs one A/B bench pass: takes bench/fixtures/<fixture>/base plus its
# diff.patch, materializes a fresh git repo in a tmpdir with the diff applied
# as an uncommitted working-tree change, then runs `claude -p` inside it to
# review that diff. Writes the raw --output-format json result to
# bench/results/<label>.json and prints a short summary.
#
# Based on the invocation pattern in the reference ab/run.sh.
set -euo pipefail

LABEL="${1:?usage: bench/run.sh <label> [fixture]}"
FIXTURE="${2:-small}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures/$FIXTURE"
BASE_DIR="$FIXTURE_DIR/base"
DIFF_FILE="$FIXTURE_DIR/diff.patch"
RESULTS_DIR="$SCRIPT_DIR/results"

if [ ! -d "$BASE_DIR" ]; then
  echo "error: fixture base not found: $BASE_DIR" >&2
  exit 1
fi
if [ ! -f "$DIFF_FILE" ]; then
  echo "error: fixture diff not found: $DIFF_FILE" >&2
  exit 1
fi

mkdir -p "$RESULTS_DIR"

TMPDIR_RUN="$(mktemp -d)"
cleanup() {
  rm -rf "$TMPDIR_RUN"
}
trap cleanup EXIT

cp -R "$BASE_DIR"/. "$TMPDIR_RUN"/

git -C "$TMPDIR_RUN" init -q
git -C "$TMPDIR_RUN" add -A
git -C "$TMPDIR_RUN" commit -q -m base
git -C "$TMPDIR_RUN" apply "$DIFF_FILE"

PROMPT='Review the uncommitted working-tree diff (git diff) of this repository for bugs. Use sub-agents: at least one to find bugs and one to validate each finding. Report only validated findings with file:line.'

OUT_FILE="$RESULTS_DIR/$LABEL.json"

(
  cd "$TMPDIR_RUN"
  claude -p "$PROMPT" --model opus --output-format json
) > "$OUT_FILE"

if command -v jq >/dev/null 2>&1; then
  SESSION_ID="$(jq -r '.session_id // empty' "$OUT_FILE" 2>/dev/null || true)"
  COST="$(jq -r '.total_cost_usd // .cost_usd // empty' "$OUT_FILE" 2>/dev/null || true)"
  DURATION_MS="$(jq -r '.duration_ms // empty' "$OUT_FILE" 2>/dev/null || true)"
  NUM_TURNS="$(jq -r '.num_turns // empty' "$OUT_FILE" 2>/dev/null || true)"

  echo "label: $LABEL"
  echo "fixture: $FIXTURE"
  echo "result_file: $OUT_FILE"
  [ -n "$SESSION_ID" ] && echo "session_id: $SESSION_ID"
  [ -n "$COST" ] && echo "total_cost_usd: $COST"
  [ -n "$DURATION_MS" ] && echo "duration_ms: $DURATION_MS"
  [ -n "$NUM_TURNS" ] && echo "num_turns: $NUM_TURNS"
else
  echo "warning: jq not found, printing raw json" >&2
  cat "$OUT_FILE"
fi
