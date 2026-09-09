#!/usr/bin/env bash
# Run one pre-labelled benchmark condition and preserve raw data + metadata.
# usage: bench/run.sh <experiment-id> <condition> <repeat> [fixture] [model]
set -euo pipefail

EXPERIMENT_ID="${1:?usage: bench/run.sh <experiment-id> <condition> <repeat> [fixture] [model]}"
CONDITION="${2:?condition is required (disabled|enabled|alternative-name)}"
REPEAT="${3:?positive repeat number is required}"
FIXTURE="${4:-small}"
MODEL="${5:-opus}"

case "$EXPERIMENT_ID" in *[!A-Za-z0-9._-]*|"") echo "error: invalid experiment id" >&2; exit 2;; esac
case "$CONDITION" in *[!A-Za-z0-9._-]*|"") echo "error: invalid condition" >&2; exit 2;; esac
case "$REPEAT" in *[!0-9]*|0|"") echo "error: repeat must be a positive integer" >&2; exit 2;; esac
case "$FIXTURE" in *[!A-Za-z0-9._-]*|"") echo "error: invalid fixture name" >&2; exit 2;; esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=../hooks/find-python.sh
. "$REPO_DIR/hooks/find-python.sh"
PY="$(find_python)" || true
if [ -z "$PY" ]; then
  echo "error: Python 3 is required for scoring and metadata" >&2
  exit 1
fi
FIXTURE_DIR="$SCRIPT_DIR/fixtures/$FIXTURE"
BASE_DIR="$FIXTURE_DIR/base"
DIFF_FILE="$FIXTURE_DIR/diff.patch"
ANSWER_FILE="$FIXTURE_DIR/ANSWER.md"
RESULTS_DIR="$SCRIPT_DIR/results/$EXPERIMENT_ID/$FIXTURE"
RUN_ID="$EXPERIMENT_ID-$FIXTURE-r$REPEAT-$CONDITION"
RAW_FILE="$RESULTS_DIR/$RUN_ID.raw.json"
STDERR_FILE="$RESULTS_DIR/$RUN_ID.stderr.txt"
SCORE_FILE="$RESULTS_DIR/$RUN_ID.score.json"
META_FILE="$RESULTS_DIR/$RUN_ID.meta.json"

for required in "$BASE_DIR" "$DIFF_FILE" "$ANSWER_FILE"; do
  if [ ! -e "$required" ]; then
    echo "error: fixture input not found: $required" >&2
    exit 1
  fi
done

mkdir -p "$RESULTS_DIR"
if [ "${TIERWORK_BENCH_OVERWRITE:-0}" != "1" ] && { [ -e "$RAW_FILE" ] || [ -e "$META_FILE" ]; }; then
  echo "error: run artifacts already exist for $RUN_ID (choose a new repeat or set TIERWORK_BENCH_OVERWRITE=1)" >&2
  exit 2
fi
TMPDIR_RUN="$(mktemp -d)"
cleanup() {
  rm -rf "$TMPDIR_RUN"
}
trap cleanup EXIT

cp -R "$BASE_DIR"/. "$TMPDIR_RUN"/
git -C "$TMPDIR_RUN" init -q
git -C "$TMPDIR_RUN" add -A
git -C "$TMPDIR_RUN" -c user.name=tierwork-bench -c user.email=bench@invalid commit -q -m base
git -C "$TMPDIR_RUN" apply "$DIFF_FILE"

PROMPT='Review the uncommitted working-tree diff (git diff) of this repository for bugs. Use sub-agents: at least one to find bugs and one to validate each finding. Report only validated findings with file:line.'
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
POLICY_REVISION="${TIERWORK_POLICY_REVISION:-$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || printf unknown)}"

SIGNAL_EXIT=0
trap 'SIGNAL_EXIT=130' INT
trap 'SIGNAL_EXIT=143' TERM
set +e
(
  cd "$TMPDIR_RUN"
  claude -p "$PROMPT" --model "$MODEL" --output-format json
) >"$RAW_FILE" 2>"$STDERR_FILE"
RUN_EXIT=$?
set -e
if [ "$SIGNAL_EXIT" -ne 0 ]; then
  RUN_EXIT="$SIGNAL_EXIT"
fi
trap - INT TERM
ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

SCORE_EXIT=0
# shellcheck disable=SC2086  # $PY may be "py -3"; intentionally unquoted
$PY "$SCRIPT_DIR/score.py" "$RAW_FILE" "$ANSWER_FILE" --json >"$SCORE_FILE" || SCORE_EXIT=$?
# shellcheck disable=SC2086  # $PY may be "py -3"; intentionally unquoted
$PY "$SCRIPT_DIR/record_run.py" \
  --raw "$RAW_FILE" --score "$SCORE_FILE" --output "$META_FILE" \
  --experiment "$EXPERIMENT_ID" --condition "$CONDITION" --repeat "$REPEAT" \
  --fixture "$FIXTURE" --model "$MODEL" --policy-revision "$POLICY_REVISION" \
  --cost-cap "${TIERWORK_BENCH_MAX_TOTAL_COST_USD:-0}" \
  --started-at "$STARTED_AT" --ended-at "$ENDED_AT" \
  --run-exit "$RUN_EXIT" --score-exit "$SCORE_EXIT"

echo "run_id: $RUN_ID"
echo "condition: $CONDITION"
echo "raw_result: $RAW_FILE"
echo "metadata: $META_FILE"

if [ "$RUN_EXIT" -ne 0 ]; then
  exit "$RUN_EXIT"
fi
exit "$SCORE_EXIT"
