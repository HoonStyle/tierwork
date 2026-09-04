# tierwork bench

Small A/B harness for comparing tierwork's review behavior with the plugin
enabled vs. disabled, using two fixture repos (`small`, `medium`) with a
known set of planted bugs.

## Running one A/B pair

```
claude plugin disable tierwork@tierwork
bench/run.sh <label-without-tierwork> [fixture]

claude plugin enable tierwork@tierwork
bench/run.sh <label-with-tierwork> [fixture]
```

`fixture` defaults to `small`; use `medium` for the larger fixture. Each run
writes `bench/results/<label>.json` (the raw `claude -p --output-format
json` payload) and prints a short summary (session_id, cost, duration,
turns) to stdout.

## Reading results

- `bench/results/*.json` — raw run output. Inspect with `jq`.
- `bench/session_usage.sh <session_id>` — per-sub-agent breakdown (agent
  type, spawn model, actual models used), a per-model token-usage totals
  table, and any gate-agent signal lines
  (`size`/`review_tier`/`validation_tier`/`changed_files`/`changed_lines`/`stake_signals`)
  found in the session.
- `bench/score.py bench/results/<label>.json bench/fixtures/<fixture>/ANSWER.md`
  — compares the `file:line` bug references in the run's report text against
  the fixture's answer key, and prints found / missed / extra.

## Caveat

Cost and duration vary run to run, and as of writing each configuration so
far has n=1 (no statistical confidence). Treat any single comparison as
anecdotal, not conclusive.
