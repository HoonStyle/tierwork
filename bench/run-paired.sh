#!/usr/bin/env bash
# Run disabled/enabled conditions in pairs. Restores the plugin to enabled.
# usage: bench/run-paired.sh <experiment-id> <fixture> <repeats> <model> <max-cost-usd>
set -uo pipefail

EXPERIMENT_ID="${1:?usage: bench/run-paired.sh <experiment-id> <fixture> <repeats> <model> <max-cost-usd>}"
FIXTURE="${2:-small}"
REPEATS="${3:-1}"
MODEL="${4:-opus}"
BUDGET_USD="${5:?maximum total cost in USD is required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=../hooks/find-python.sh
. "$REPO_DIR/hooks/find-python.sh"
PY="$(find_python)" || true
if [ -z "$PY" ]; then
  echo "error: Python 3 is required for budget enforcement" >&2
  exit 1
fi
PLUGIN_REF="${TIERWORK_BENCH_PLUGIN_REF:-tierwork@tierwork}"
export TIERWORK_BENCH_MAX_TOTAL_COST_USD="$BUDGET_USD"

case "$REPEATS" in *[!0-9]*|0|"") echo "error: repeats must be a positive integer" >&2; exit 2;; esac
case "$EXPERIMENT_ID" in *[!A-Za-z0-9._-]*|"") echo "error: invalid experiment id" >&2; exit 2;; esac
case "$FIXTURE" in *[!A-Za-z0-9._-]*|"") echo "error: invalid fixture name" >&2; exit 2;; esac

restore_enabled() {
  claude plugin enable "$PLUGIN_REF" >/dev/null 2>&1 || true
}
trap restore_enabled EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

failures=0
budget_stop=0
# Validate the cap before the first paid invocation.
# shellcheck disable=SC2086  # $PY may be "py -3"; intentionally unquoted
$PY "$SCRIPT_DIR/budget.py" "$SCRIPT_DIR/results/$EXPERIMENT_ID/$FIXTURE" "$BUDGET_USD" || exit $?
for repeat in $(seq 1 "$REPEATS"); do
  if [ $((repeat % 2)) -eq 1 ]; then
    CONDITIONS="disabled enabled"
  else
    CONDITIONS="enabled disabled"
  fi
  for condition in $CONDITIONS; do
    action="disable"
    [ "$condition" = "enabled" ] && action="enable"
    if ! claude plugin "$action" "$PLUGIN_REF"; then
      echo "error: could not set $PLUGIN_REF to $condition for pair $repeat" >&2
      failures=$((failures + 1))
      break
    fi
    "$SCRIPT_DIR/run.sh" "$EXPERIMENT_ID" "$condition" "$repeat" "$FIXTURE" "$MODEL" || failures=$((failures + 1))
    # shellcheck disable=SC2086  # $PY may be "py -3"; intentionally unquoted
    if ! $PY "$SCRIPT_DIR/budget.py" "$SCRIPT_DIR/results/$EXPERIMENT_ID/$FIXTURE" "$BUDGET_USD"; then
      budget_stop=1
      break 2
    fi
  done
done

echo "pairs requested: $REPEATS"
echo "failed condition runs: $failures"
echo "budget stop: $budget_stop"
echo "results: $SCRIPT_DIR/results/$EXPERIMENT_ID/$FIXTURE"
[ "$failures" -eq 0 ] && [ "$budget_stop" -eq 0 ]
