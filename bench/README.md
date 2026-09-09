# tierwork bench

Small A/B harness for comparing tierwork's review behavior with the plugin
enabled vs. disabled, using two fixture repos (`small`, `medium`) with a
known set of planted bugs.

## Running paired repeats

Before the first paid run, copy `experiment.example.json`, choose the minimum
pair count and claim thresholds, and keep that config unchanged for the
experiment. Set its `maximum_total_cost_usd` to the same cap passed to
`run-paired.sh`. Null thresholds force an `inconclusive` conclusion.

```bash
cp bench/experiment.example.json bench/experiment-my-study.json
# edit thresholds before collecting data
bench/run-paired.sh <experiment-id> <fixture> <repeats> <model> <max-cost-usd>
```

`fixture` may be `small` or `medium`; repeat count, model, and a positive total
cost cap are explicit inputs. The cap is checked after every condition run;
missing cost data or reaching the cap stops further paid runs and leaves the
unfinished pair visible.
`run-paired.sh` runs `disabled` then `enabled` on odd repeats and uses the
inverse order on even repeats to reduce fixed-order bias; it restores
`tierwork@tierwork` to enabled on exit. Each condition gets a distinct raw
result, stderr, location score, and metadata envelope under
`bench/results/<experiment>/<fixture>/`. Failed condition runs still produce
metadata and remain visible to aggregation. Use a separate experiment ID for
an alternative policy; never pool it with the fixed-policy cohort.

For manual condition control, run one condition without changing plugin state:

```bash
bench/run.sh <experiment-id> <condition> <repeat> [fixture] [model]
```

## Reading results

- `bench/results/**/*.raw.json` — immutable raw Claude output; metadata stores
  its SHA-256.
- `*.meta.json` — fixture, condition, repeat, main model, policy revision,
  timestamps, exit status, raw metrics, and the linked location score.
- `bench/session_usage.sh <session_id>` — per-sub-agent breakdown (agent
  type, spawn model, actual models used), a per-model token-usage totals
  table, and any gate-agent signal lines
  (`size`/`review_tier`/`validation_tier`/`changed_files`/`changed_lines`/`stake_signals`)
  found in the session.
- `bench/score.py <raw.json> bench/fixtures/<fixture>/ANSWER.md [--json]`
  — classifies exact/range/outside/duplicate/ambiguous location candidates.
  Answer entries pre-register `ID|path:allowed-range|condition|expected`.
  Location overlap never confirms semantic correctness: a reviewer must judge
  whether the claim actually describes that defect, and same-line false claims
  remain `semantic_review_required`. An independent reviewer can finalize the
  score with `--judgments review.json`; every extracted reference must receive
  `true_positive`, `false_positive`, or `unknown`, and a true positive must name
  one of that reference's location-candidate answer IDs:

  ```json
  {
    "reviewer": "reviewer-id",
    "independent": true,
    "references": [
      {"index": 0, "verdict": "true_positive", "answer_id": "small-filter"},
      {"index": 1, "verdict": "false_positive", "note": "wrong causal claim"}
    ]
  }
  ```

  Re-run the scorer with `--json --judgments review.json` into the run's same
  `*.score.json` path. Aggregation reads the current sidecar score, so the raw
  result and metadata envelope stay intact.
- `bench/aggregate.py <metadata-file-or-dir> --config <experiment.json>`
  — reports completed pair count, failed/unpaired runs, mean/median/sample
  standard deviation, paired cost improvement, and location-recall delta.
  It cannot return `supported` until minimum sample and cost/quality thresholds
  were preregistered and every included score has independent semantic review
  marked complete.

## Dashboard

`bench/status.py` provides a one-shot, stdlib-only diagnostic view suitable
for a person or parent agent:

```bash
python3 bench/status.py [--log ~/.tierwork/reviews.jsonl] [--session ID] [--agent ID]
python3 bench/status.py --session ID --json
```

It reports all latest recorded `running` rows, completions recorded within the
last five minutes by default, unknown statuses, and malformed/missing/unreadable
input diagnostics. Its merge is deliberately assignment-oriented: the newest
valid timestamp wins for one `session_id`+`agent_id`, so a newer resumed start
is not hidden by an older completion; a same-time completion wins a start.
The dashboard, exports, SSE upsert, and offline merge use the same rule. Output
is recorded hook status only—not
process liveness, success, result retrieval, or parent integration. Missing
rows are inconclusive, future-dated completions are diagnostic rather than
recent, and assignment generation is unavailable.

Run all stdlib regression tests from the repository root with:

```bash
python3 -m unittest discover -s bench -p 'test_*.py' -v
```

The suite covers recorded-state merging, SSE byte boundaries, status CLI
contracts, and Claude/Codex hook fixtures, including concurrent Python-hook
writers. Native POSIX Bash is required for
the forced minimal-fallback fixture; that single case is skipped on Windows.

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
from), and de-duplicated across files by `session_id`+`agent_id`. The dedup
rule is the latest valid recorded `ts` for each key; only at the same
timestamp does a `"done"` row (or a legacy row with no `status` field) win
over another state. Unknown/future statuses remain unknown and are not
counted as completed runs. Rows missing a usable identity or timestamp are
excluded rather than guessed. This rule is applied identically by `/api/rows`,
`/api/export.json`, `/api/export.csv`, the SSE append/broadcast logic, and
`bench/merge.py`. It describes recorded hook history, not process liveness;
assignment generation is not available and is never synthesized. `--labels`
stays a single file — labels are always this machine's own labels file.

then open the printed `http://127.0.0.1:<port>` URL. The page ("tierwork
mission control") loads real data from `/api/rows` on open and stays live
after that via Server-Sent Events (`/api/events`) — no sample-data generator,
no external fonts or CDN, all local fallback font stacks. It shows a KPI
strip (sub-agent runs, validators confirmed, needs-primary-review share,
output tokens, estimated cost, labeled share), review swimlanes (one lane per
`agent_type`, an inline-SVG mark per run sized by output tokens and shaped/
colored by model tier — haiku/sonnet/opus, with an "unknown" hollow-grey mark
when the tier can't be determined from `spawn_model`/`models`), a live feed
of recent runs, a tier cost bar (haiku/sonnet/opus list price per 1M output
tokens — list price, not spend), a verdict funnel, and a runs table with
inline TP/FP label buttons. In-flight (`status: "running"`) sub-agent runs
are rendered too: a hollow, softly pulsing mark on the swimlane at the run's
start `ts` (no end `ts` yet), a "running · Xs" live-feed line with a
client-side elapsed-seconds ticker (no server polling needed), and a dashed,
muted "running" chip in the runs table verdict column. The "Sub-agent runs"
KPI counts only `"done"`/legacy rows, never `"running"` ones, and a small
"in flight: N" line under the LIVE/SSE status label shows the current count
of running rows. When a run's `"done"` record arrives over SSE for a key
that currently shows a `"running"` row, it replaces that row in place and
replays the normal SSE "new row" enter animation. A 24h / 7d / all segmented control filters
everything client-side by `ts` and adapts the swimlane time-axis ticks to
match. The server process itself is a `ThreadingHTTPServer` (rather than a
plain `HTTPServer`) so a long-lived SSE connection doesn't block other
requests. If the log(s) are empty, the swimlane panel shows an inline "No
runs yet…" message instead of an empty chart, and the KPIs read "—".

Routes:

- `GET /` — the dashboard page.
- `GET /api/rows` — the merged log (all `--log` sources, deduped) as JSON,
  merged with the latest label (by `session_id`+`agent_id`) from the labels
  file. Malformed lines in any file are skipped; a missing log or labels file
  is treated as empty. Each row carries `source`, and label fields are
  exposed as `label` / `label_note` / `label_ts`.
- `GET /api/events` — a Server-Sent Events stream. Sends `event: hello` on
  connect, then `event: rows` with a JSON array of newly appended (and
  label-merged) rows whenever a background thread notices one of the `--log`
  files has grown. The once-per-second watcher tracks byte offset, file
  identity, and incomplete bytes per file, and emits only newline-terminated
  UTF-8 JSONL records. Split writes and multibyte characters are retained until
  complete; truncate/rotation clears the old fragment. There is no history
  replay, only rows appended after the server started. Sends a
  `: ping` comment every 15s to keep idle connections alive. The page falls
  back to polling `/api/rows` every 10s if the SSE connection drops, and
  switches back to SSE automatically on reconnect.
- `GET /api/diagnostics` — counters for complete watcher records skipped as
  malformed JSON, invalid UTF-8, or non-object JSON. Incomplete records are
  pending data and are not counted as errors.
- `GET /api/export.json` — the same merged rows as `/api/rows`, served as a
  file download (`Content-Disposition: attachment`) named
  `tierwork-export-<hostname>-<YYYYMMDD>.json`.
- `GET /api/export.csv` — the same merged rows as CSV, fixed column order
  `ts, status, session_id, agent_id, agent_type, runtime, spawn_model,
  models, msgs, tool_calls, input_tokens, output_tokens, cache_read,
  cache_create, verdict, confidence, check_status, needs_primary_review,
  proceed, description, cwd, source, label, label_note, label_ts` (`models`
  joined with `|`; missing
  fields empty), downloaded as
  `tierwork-export-<hostname>-<YYYYMMDD>.csv`.
- `POST /api/label` — body `{"session_id", "agent_id", "label", "note"}`
  with `label` one of `true_positive` / `false_positive` / `unclear`.
  Appends one JSON line (with a server-set `label_ts`) to the labels file.
  (The on-disk labels file still uses the field name `note`; only the
  merged/exported row output renames it to `label_note`.)

`tierwork:bug-validator` rows in the table get TP/FP label buttons, for
manually reviewing whether the validator's `verdict` was actually right.
Labels are stored separately from the log itself, in
`~/.tierwork/labels.jsonl` by default (append-only; the latest line for a
given session_id+agent_id wins), so labeling never touches the hook-written
log file. A label posted from another tab shows up here on the next SSE
`rows` event or reload.

**Status: new, not yet used for a real labeling pass** — the server, routes,
and rendering have been smoke-tested (`py_compile`, a live `curl` round-trip
against `/api/rows`, `/api/events`, `/api/label`, `/api/export.json`, and
`/api/export.csv`, including appending a line to a watched log file and
confirming it arrives as an `event: rows` SSE frame), but no one has sat down
and labeled a real batch of validator rows with it yet.

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
anecdotal, not conclusive. The new paired harness has not yet been run: no
minimum pair count or cost budget has been selected, so current evidence stays
`inconclusive`. Raw output and location matches are reproducible inputs, not an
automated truth oracle.
