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

## Dashboard

`bench/dashboard.py` is a small local review dashboard for the
`SubagentStop` data log (`~/.tierwork/reviews.jsonl` by default; see the main
README's "Data log" section for how that log is produced). Stdlib only
(`http.server`, `json`, `pathlib`, `argparse`, `datetime`) — no third-party
deps, no CDN, no external network calls. It binds to `127.0.0.1` only.

Run it with:

```
python3 bench/dashboard.py [--log ~/.tierwork/reviews.jsonl] [--labels ~/.tierwork/labels.jsonl] [--port 8765]
```

then open the printed `http://127.0.0.1:<port>` URL. The page shows stat
tiles (total runs, validator runs, confirmed share, `needs_primary_review`
share, total output tokens, labeled share — computed the same way
`bench/report.py` computes them, so the two should agree on the same log), a
bar chart of output tokens per `agent_type` (colored by model tier), a
line/dot chart of output tokens per run over time (colored by `agent_type`),
and a table of every row, newest first.

Routes:

- `GET /` — the dashboard page.
- `GET /api/rows` — the log, JSON-decoded and merged with the latest label
  (by `session_id`+`agent_id`) from the labels file. Malformed lines in
  either file are skipped; a missing log or labels file is treated as empty.
- `POST /api/label` — body `{"session_id", "agent_id", "label", "note"}`
  with `label` one of `true_positive` / `false_positive` / `unclear`.
  Appends one JSON line (with a server-set `label_ts`) to the labels file.

`tierwork:bug-validator` rows in the table get true_positive/false_positive/
unclear label buttons plus an optional note field, for manually reviewing
whether the validator's `verdict` was actually right. Labels are stored
separately from the log itself, in `~/.tierwork/labels.jsonl` by default
(append-only; the latest line for a given session_id+agent_id wins), so
labeling never touches the hook-written log file.

**Status: new, not yet used for a real labeling pass** — the server, routes,
and rendering have been smoke-tested (`py_compile`, a live `curl` round-trip
against `/api/rows` and `/api/label`), but no one has sat down and labeled a
real batch of validator rows with it yet.

## Caveat

Cost and duration vary run to run, and as of writing each configuration so
far has n=1 (no statistical confidence). Treat any single comparison as
anecdotal, not conclusive.
