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

`--log` may be given multiple times, and each value may be a file or a
directory (directories are globbed non-recursively for `*.jsonl`, sorted for
determinism). With no `--log` at all it falls back to `TIERWORK_LOG` or
`~/.tierwork/reviews.jsonl`, same as before. Rows from all resolved files are
loaded, each tagged with a `source` field (the basename of the file it came
from), and de-duplicated across files by `session_id`+`agent_id`, keeping the
row with the latest `ts`. `--labels` stays a single file — labels are always
this machine's own labels file.

then open the printed `http://127.0.0.1:<port>` URL. The page shows stat
tiles (total runs, validator runs, confirmed share, `needs_primary_review`
share, total output tokens, labeled share — computed the same way
`bench/report.py` computes them, so the two should agree on the same log), a
bar chart of output tokens per `agent_type` (colored by model tier), a
line/dot chart of output tokens per run over time (colored by `agent_type`),
a table of every row (newest first), and — under the subtitle — a "Sources:"
line listing the distinct `source` basenames actually present in the loaded
data (or "No data loaded").

Routes:

- `GET /` — the dashboard page.
- `GET /api/rows` — the merged log (all `--log` sources, deduped) as JSON,
  merged with the latest label (by `session_id`+`agent_id`) from the labels
  file. Malformed lines in any file are skipped; a missing log or labels file
  is treated as empty. Each row carries `source`, and label fields are
  exposed as `label` / `label_note` / `label_ts`.
- `GET /api/export.json` — the same merged rows as `/api/rows`, served as a
  file download (`Content-Disposition: attachment`) named
  `tierwork-export-<hostname>-<YYYYMMDD>.json`.
- `GET /api/export.csv` — the same merged rows as CSV, fixed column order
  `ts, session_id, agent_id, agent_type, spawn_model, models, msgs,
  tool_calls, input_tokens, output_tokens, cache_read, cache_create,
  verdict, confidence, needs_primary_review, proceed, description, cwd,
  source, label, label_note, label_ts` (`models` joined with `|`; missing
  fields empty), downloaded as
  `tierwork-export-<hostname>-<YYYYMMDD>.csv`.
- `POST /api/label` — body `{"session_id", "agent_id", "label", "note"}`
  with `label` one of `true_positive` / `false_positive` / `unclear`.
  Appends one JSON line (with a server-set `label_ts`) to the labels file.
  (The on-disk labels file still uses the field name `note`; only the
  merged/exported row output renames it to `label_note`.)

`tierwork:bug-validator` rows in the table get true_positive/false_positive/
unclear label buttons plus an optional note field, for manually reviewing
whether the validator's `verdict` was actually right. Labels are stored
separately from the log itself, in `~/.tierwork/labels.jsonl` by default
(append-only; the latest line for a given session_id+agent_id wins), so
labeling never touches the hook-written log file.

**Status: new, not yet used for a real labeling pass** — the server, routes,
and rendering have been smoke-tested (`py_compile`, a live `curl` round-trip
against `/api/rows`, `/api/label`, `/api/export.json`, and `/api/export.csv`),
but no one has sat down and labeled a real batch of validator rows with it
yet.

### Cross-machine merge (`bench/merge.py`)

`bench/merge.py` combines review logs collected on different machines into
one de-duped JSONL file, reusing the same file/directory expansion and
`(session_id, agent_id)`-latest-`ts`-wins de-dup rule as `--log`. Stdlib
only, does not start any server:

```
python3 bench/merge.py in1.jsonl [in2.jsonl|dir ...] -o merged.jsonl
```

Prints the number of input files, total rows read, and rows written after
de-dup, and writes the merged rows (each tagged with `source`) as JSONL.

Workflow for viewing two machines' data together:

1. On machine A, export machine A's data — either run the dashboard there
   and hit `/api/export.json` or `/api/export.csv` for a copy that carries
   along that machine's labels, or just copy its raw
   `~/.tierwork/reviews.jsonl`.
2. Copy the exported/raw file to machine B.
3. On machine B, merge it with machine B's own log and view both together:
   ```
   bench/merge.py <machineA-export> ~/.tierwork/reviews.jsonl -o merged.jsonl
   python3 bench/dashboard.py --log merged.jsonl
   ```
   (or skip the merge step and pass both files directly with two `--log`
   flags — `bench/dashboard.py` does the same dedup internally.)

Labels are per-machine: each dashboard instance only ever reads labels from
its own `--labels` file, so a raw `~/.tierwork/reviews.jsonl` copied between
machines carries no labels. Once you've exported via `/api/export.json` or
`/api/export.csv`, though, that machine's labels travel inside the exported
rows' `label`/`label_note`/`label_ts` fields — no separate labels file needs
to move, and `bench/merge.py`/`--log` will carry them straight through.

## Caveat

Cost and duration vary run to run, and as of writing each configuration so
far has n=1 (no statistical confidence). Treat any single comparison as
anecdotal, not conclusive.
