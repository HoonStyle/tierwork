#!/usr/bin/env python3
"""Local review dashboard for tierwork's SubagentStop log.

Usage:
    bench/dashboard.py [--log ~/.tierwork/reviews.jsonl]
                        [--labels ~/.tierwork/labels.jsonl]
                        [--port 8765]

Serves a single self-contained HTML page (stdlib http.server only, no
third-party deps, no CDN or other external network calls, no Google Fonts)
with a KPI strip, review swimlanes (inline SVG), a live feed, a tier cost
bar, a verdict funnel, and a sortable table of every logged tierwork
sub-agent run. Binds to 127.0.0.1 only.

Routes:
    GET  /            the dashboard page
    GET  /api/rows    JSON array: log rows merged with the latest label
                       (by session_id+agent_id) from the labels file
    GET  /api/events  Server-Sent Events stream of newly appended rows,
                       polled from the --log file(s) every second
    POST /api/label   body {"session_id", "agent_id", "label", "note"};
                       appends one JSON line to the labels file

Field names, verdict values, and the needs_primary_review convention
("yes"/other, case-insensitive string) are read the same way bench/report.py
reads them, so shares shown here match report.py's numbers on the same log.
"""

import argparse
import csv
import io
import json
import os
import queue
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VALID_LABELS = {"true_positive", "false_positive", "unclear"}

CSV_COLUMNS = [
    "ts", "session_id", "agent_id", "agent_type", "spawn_model", "models",
    "msgs", "tool_calls", "input_tokens", "output_tokens", "cache_read",
    "cache_create", "verdict", "confidence", "needs_primary_review",
    "proceed", "description", "cwd", "source", "label", "label_note",
    "label_ts",
]

# How often the SSE background thread checks log files for new bytes.
POLL_INTERVAL_SECONDS = 1.0
# How often an idle SSE connection gets a comment-only keepalive ping.
SSE_PING_SECONDS = 15.0


def default_log_path():
    env = os.environ.get("TIERWORK_LOG")
    if env:
        return env
    return "~/.tierwork/reviews.jsonl"


def resolve_log_files(paths):
    """Expand a list of --log values (files or directories) into a sorted,
    deterministic list of files to load. Directories are globbed
    non-recursively for *.jsonl."""
    files = []
    for p in paths:
        path = Path(os.path.expanduser(str(p)))
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        else:
            files.append(path)
    return files


def load_jsonl_multi(paths):
    """Load rows from every resolved file, tagging each with source =
    basename of the file it came from."""
    rows = []
    for path in resolve_log_files(paths):
        for row in load_jsonl(path):
            row = dict(row)
            row["source"] = Path(path).name
            rows.append(row)
    return rows


def _parse_ts(row):
    ts = row.get("ts")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _status_rank(row):
    """Win-tier for the merge rule: a "done" row (or a legacy row with no
    `status` field at all, since it predates the SubagentStart hook) always
    outranks a "running" row. Returns 1 for done/legacy, 0 for running."""
    status = row.get("status")
    if status is None or status == "done":
        return 1
    if status == "running":
        return 0
    # Unknown/future status values: treat like done/legacy (highest rank)
    # rather than silently losing to a running row.
    return 1


def dedup_rows(rows):
    """De-duplicate rows by (session_id, agent_id).

    Merge rule: a row's win-tier (`_status_rank`) is compared first -- a
    "done"/legacy row always beats a "running" row sharing the same key,
    regardless of `ts`. Among rows sharing both the same key and the same
    win-tier, the row with the latest parsed `ts` wins; rows with a
    missing/unparseable ts are treated as the lowest priority within their
    tier. On a tie (or comparison error), the later-loaded row wins. Pure
    function, order of `rows` matters only as a tie-breaker."""
    best = {}
    order = {}
    for i, row in enumerate(rows):
        key = (row.get("session_id"), row.get("agent_id"))
        rank = _status_rank(row)
        parsed = _parse_ts(row)
        current = best.get(key)
        if current is None:
            best[key] = row
            order[key] = (rank, parsed, i)
            continue
        cur_rank, cur_parsed, cur_i = order[key]
        take_new = False
        if rank != cur_rank:
            take_new = rank > cur_rank
        # Same win-tier: latest ts wins; None (unparseable) sorts lowest;
        # ties/later-loaded win.
        elif parsed is None and cur_parsed is None:
            take_new = i >= cur_i
        elif parsed is None:
            take_new = False
        elif cur_parsed is None:
            take_new = True
        elif parsed > cur_parsed:
            take_new = True
        elif parsed == cur_parsed:
            take_new = i >= cur_i
        if take_new:
            best[key] = row
            order[key] = (rank, parsed, i)
    return list(best.values())


def load_jsonl(path: Path):
    """Tolerant JSONL reader: skip malformed lines and non-object rows.
    Missing file -> empty list."""
    rows = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def load_labels(path: Path):
    """Key = (session_id, agent_id). Later lines override earlier ones."""
    labels = {}
    for obj in load_jsonl(path):
        key = (obj.get("session_id"), obj.get("agent_id"))
        labels[key] = obj
    return labels


def row_key(row):
    """The dedup/identity key used everywhere a row needs to be addressed:
    /api/rows dedup, label merge, and SSE de-dup against already-seen rows."""
    return (row.get("session_id"), row.get("agent_id"))


def _apply_label(row, labels):
    lab = labels.get(row_key(row))
    if lab:
        row["label"] = lab.get("label")
        row["label_note"] = lab.get("note")
        row["label_ts"] = lab.get("label_ts")
    else:
        row["label"] = None
        row["label_note"] = None
        row["label_ts"] = None
    return row


def merged_rows(log_paths, labels_path: Path):
    """log_paths: a single path or a list of paths (files or directories)."""
    if isinstance(log_paths, (str, Path)):
        log_paths = [log_paths]
    rows = dedup_rows(load_jsonl_multi(log_paths))
    labels = load_labels(labels_path)
    out = []
    for r in rows:
        row = dict(r)
        _apply_label(row, labels)
        out.append(row)
    return out


def rows_to_csv(rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        vals = []
        for col in CSV_COLUMNS:
            if col == "models":
                m = row.get("models")
                if isinstance(m, list):
                    vals.append("|".join(str(x) for x in m))
                else:
                    vals.append(str(m) if m else "")
            else:
                vals.append(row.get(col, ""))
        writer.writerow(vals)
    return buf.getvalue()


def export_filename(ext: str) -> str:
    host = socket.gethostname()
    date = datetime.now().strftime("%Y%m%d")
    return f"tierwork-export-{host}-{date}.{ext}"


class LogTailer:
    """Background poll thread: watches --log file(s) for appended bytes,
    parses newly appended JSONL lines, merges them with labels the same way
    /api/rows does, and fans the resulting row dicts out to every connected
    SSE client as `event: rows` frames.

    File growth is tracked by byte offset per resolved path. On startup each
    file is baselined at its current size (no history replay over SSE --
    /api/rows already serves the full history on initial page load).
    """

    def __init__(self, log_paths, labels_path: Path):
        self.log_paths = log_paths
        self.labels_path = labels_path
        self._offsets = {}
        self._clients = []
        self._clients_lock = threading.Lock()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def add_client(self):
        q = queue.Queue()
        with self._clients_lock:
            self._clients.append(q)
        return q

    def remove_client(self, q):
        with self._clients_lock:
            if q in self._clients:
                self._clients.remove(q)

    def _broadcast(self, event: str, data_obj):
        payload = f"event: {event}\ndata: {json.dumps(data_obj, ensure_ascii=False)}\n\n"
        with self._clients_lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def _run(self):
        while True:
            try:
                self._poll_once()
            except Exception:
                # Never let a transient parse/IO error kill the poll thread.
                pass
            time.sleep(POLL_INTERVAL_SECONDS)

    def _poll_once(self):
        files = resolve_log_files(self.log_paths)
        labels = None  # loaded lazily, once, only if some file actually grew
        for path in files:
            key = str(path)
            try:
                size = path.stat().st_size if path.is_file() else 0
            except OSError:
                size = 0

            if key not in self._offsets:
                # First time we see this file: baseline at current size so
                # we only stream rows appended *after* server startup.
                self._offsets[key] = size
                continue

            old = self._offsets[key]
            if size < old:
                # Truncated or rotated underneath us; reset and move on.
                self._offsets[key] = size
                continue
            if size == old:
                continue

            try:
                with path.open("rb") as f:
                    f.seek(old)
                    chunk = f.read()
                self._offsets[key] = old + len(chunk)
            except OSError:
                continue

            text = chunk.decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                continue

            if labels is None:
                labels = load_labels(self.labels_path)

            new_rows = []
            for line in lines:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                row = dict(obj)
                row["source"] = path.name
                _apply_label(row, labels)
                new_rows.append(row)

            if new_rows:
                self._broadcast("rows", new_rows)


def make_handler(log_paths, labels_path: Path, tailer: LogTailer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TierworkDashboard/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            # Keep stdout limited to the startup URL line; suppress the
            # default per-request access log noise.
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str, status=200):
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_download(self, body: bytes, content_type: str, filename: str, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def _handle_sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            q = tailer.add_client()
            try:
                hello = {
                    "time": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z")
                }
                self.wfile.write(
                    f"event: hello\ndata: {json.dumps(hello)}\n\n".encode("utf-8")
                )
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=SSE_PING_SECONDS)
                        self.wfile.write(msg.encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError, ConnectionAbortedError):
                pass
            finally:
                tailer.remove_client(q)

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/?"):
                self._send_html(PAGE_HTML)
            elif self.path == "/api/rows" or self.path.startswith("/api/rows?"):
                try:
                    rows = merged_rows(log_paths, labels_path)
                    self._send_json(rows)
                except Exception as e:
                    self._send_json({"error": str(e)}, status=500)
            elif self.path == "/api/events":
                try:
                    self._handle_sse()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            elif self.path == "/api/export.json":
                try:
                    rows = merged_rows(log_paths, labels_path)
                    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
                    self._send_download(
                        body, "application/json; charset=utf-8", export_filename("json")
                    )
                except Exception as e:
                    self._send_json({"error": str(e)}, status=500)
            elif self.path == "/api/export.csv":
                try:
                    rows = merged_rows(log_paths, labels_path)
                    body = rows_to_csv(rows).encode("utf-8")
                    self._send_download(
                        body, "text/csv; charset=utf-8", export_filename("csv")
                    )
                except Exception as e:
                    self._send_json({"error": str(e)}, status=500)
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self):
            if self.path != "/api/label":
                self._send_json({"error": "not found"}, status=404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json({"error": "invalid JSON body"}, status=400)
                return
            if not isinstance(body, dict):
                self._send_json({"error": "invalid JSON body"}, status=400)
                return

            session_id = body.get("session_id")
            agent_id = body.get("agent_id")
            label = body.get("label")
            note = body.get("note")

            if label not in VALID_LABELS:
                self._send_json(
                    {
                        "error": "label must be one of: "
                        + ", ".join(sorted(VALID_LABELS))
                    },
                    status=400,
                )
                return

            record = {
                "session_id": session_id,
                "agent_id": agent_id,
                "label": label,
                "note": note if isinstance(note, str) else "",
                "label_ts": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            }

            try:
                labels_path.parent.mkdir(parents=True, exist_ok=True)
                with labels_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as e:
                self._send_json({"error": f"could not write labels file: {e}"}, status=500)
                return

            self._send_json(record, status=200)

    return Handler


PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>tierwork mission control</title>
<style>
  :root {
    --bg: #0B1220; --panel: #111B2E; --panel-2: #0E1728; --line: #24324A; --line-soft: #1A2539;
    --text: #E6EDF7; --muted: #8B9BB4; --dim: #5B6B85;
    --haiku: #7DD3A8; --sonnet: #60A5FA; --opus: #F59E0B; --unknown: #5B6B85;
    --ok: #34D399; --bad: #FB7185; --warn: #FBBF24; --live: #FFFFFF;
    --display: "Chakra Petch", "Segoe UI", system-ui, sans-serif;
    --body: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
    --mono: "IBM Plex Mono", "SF Mono", Menlo, Consolas, monospace;
    --r: 6px; --gap: 16px;
  }
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
      --bg: #F3F6FB; --panel: #FFFFFF; --panel-2: #F7F9FD; --line: #CBD5E4; --line-soft: #E3E9F2;
      --text: #0F1A2E; --muted: #526078; --dim: #8593AA;
      --haiku: #1E9E63; --sonnet: #2563EB; --opus: #C2410C; --unknown: #8593AA;
      --ok: #059669; --bad: #E11D48; --warn: #B45309; --live: #0F1A2E;
    }
  }
  :root[data-theme="light"] {
    --bg: #F3F6FB; --panel: #FFFFFF; --panel-2: #F7F9FD; --line: #CBD5E4; --line-soft: #E3E9F2;
    --text: #0F1A2E; --muted: #526078; --dim: #8593AA;
    --haiku: #1E9E63; --sonnet: #2563EB; --opus: #C2410C; --unknown: #8593AA;
    --ok: #059669; --bad: #E11D48; --warn: #B45309; --live: #0F1A2E;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 var(--body); }
  a { color: inherit; }
  .num { font-family: var(--mono); font-variant-numeric: tabular-nums; }
  .wrap { max-width: 1440px; margin: 0 auto; padding: 20px 24px 48px; display: grid; gap: var(--gap); }

  /* top bar */
  .top { display: flex; align-items: center; gap: 20px; padding: 10px 0 6px; border-bottom: 1px solid var(--line-soft); flex-wrap: wrap; }
  .brand { display: flex; align-items: baseline; gap: 10px; }
  .brand h1 { font: 700 20px/1 var(--display); letter-spacing: .04em; margin: 0; text-transform: uppercase; }
  .brand span { font-family: var(--mono); color: var(--muted); font-size: 12px; }
  .status { display: flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 12px; color: var(--muted); }
  .status-col { display: flex; flex-direction: column; gap: 1px; line-height: 1.25; }
  .inflight { font-size: 10px; color: var(--dim); }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--live); box-shadow: 0 0 0 0 rgba(255,255,255,.5); animation: pulse 1.6s ease-out infinite; }
  .pulse.stale { background: var(--warn); animation: none; }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(255,255,255,.45);} 100% { box-shadow: 0 0 0 10px rgba(255,255,255,0);} }
  .spacer { flex: 1; }
  .btn { font: 500 12px var(--body); color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: var(--r); padding: 6px 12px; cursor: pointer; }
  .btn:hover { border-color: var(--muted); }
  .btn:focus-visible, .row:focus-visible, .dot:focus-visible { outline: 2px solid var(--sonnet); outline-offset: 2px; }
  .btn.primary { border-color: var(--opus); color: var(--opus); }
  .seg { display: inline-flex; border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; }
  .seg button { font: 500 12px var(--body); color: var(--muted); background: var(--panel); border: 0; border-right: 1px solid var(--line); padding: 6px 12px; cursor: pointer; }
  .seg button:last-child { border-right: 0; }
  .seg button.on { color: var(--text); background: var(--panel-2); }
  .seg button:hover { color: var(--text); }
  a.dl { font: 500 12px var(--body); color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: var(--r); padding: 6px 12px; text-decoration: none; }
  a.dl:hover { border-color: var(--muted); }

  /* kpi strip */
  .kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: var(--gap); }
  .kpi { background: var(--panel); border: 1px solid var(--line-soft); border-radius: var(--r); padding: 12px 14px 10px; position: relative; overflow: hidden; }
  .kpi .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
  .kpi .val { font: 600 28px/1.1 var(--display); margin-top: 4px; position: relative; z-index: 1; }
  .kpi .sub { font-family: var(--mono); font-size: 11px; color: var(--muted); margin-top: 2px; white-space: nowrap; position: relative; z-index: 1; }
  .kpi .sub.up { color: var(--ok); } .kpi .sub.down { color: var(--bad); }
  .kpi.hero { border-color: var(--opus); }
  .kpi.hero .val { color: var(--opus); }

  /* panels */
  .panel { background: var(--panel); border: 1px solid var(--line-soft); border-radius: var(--r); }
  .panel > header { display: flex; align-items: baseline; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--line-soft); flex-wrap: wrap; }
  .panel > header h2 { font: 600 14px/1 var(--display); letter-spacing: .06em; text-transform: uppercase; margin: 0; }
  .panel > header .meta { font-family: var(--mono); font-size: 11px; color: var(--muted); }
  .panel > header .spacer { flex: 1; }
  .legend { display: flex; gap: 14px; font-family: var(--mono); font-size: 11px; color: var(--muted); }
  .legend i { display: inline-block; width: 9px; height: 9px; margin-right: 6px; vertical-align: -1px; }
  .legend .haiku i { background: var(--haiku); border-radius: 50%; }
  .legend .sonnet i { background: var(--sonnet); }
  .legend .opus i { background: var(--opus); transform: rotate(45deg) scale(.85); }
  .legend .unknown i { border: 1px solid var(--unknown); border-radius: 50%; background: transparent; }

  /* hero grid: timeline + feed */
  .hero { display: grid; grid-template-columns: 1fr 320px; gap: var(--gap); }
  .lanes { padding: 8px 0 12px; overflow-x: auto; }
  .lanes svg { width: 100%; height: 300px; display: block; }
  .lane-lbl { font: 600 11px var(--display); letter-spacing: .08em; fill: var(--muted); text-transform: uppercase; }
  .grid-l { stroke: var(--line-soft); stroke-width: 1; }
  .axis-t { font: 10px var(--mono); fill: var(--dim); }
  .dot { cursor: pointer; }
  .dot.enter { animation: slidein .5s cubic-bezier(.2,.8,.2,1) both; }
  @keyframes slidein { from { transform: translateX(40px); opacity: 0; } to { transform: none; opacity: 1; } }
  .dot.running { animation: dotpulse 1.6s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
  @keyframes dotpulse { 0%, 100% { opacity: .55; transform: scale(1); } 50% { opacity: 1; transform: scale(1.18); } }
  .tip { position: absolute; pointer-events: none; background: var(--panel-2); border: 1px solid var(--line); border-radius: var(--r); padding: 8px 10px; font: 11px/1.5 var(--mono); color: var(--text); white-space: nowrap; box-shadow: 0 8px 24px rgba(0,0,0,.35); }

  .feed { display: flex; flex-direction: column; max-height: 360px; overflow-y: auto; }
  .feed ol { list-style: none; margin: 0; padding: 6px 0; }
  .feed li { display: grid; grid-template-columns: 10px 1fr auto; gap: 10px; align-items: start; padding: 8px 14px; border-bottom: 1px solid var(--line-soft); }
  .feed li.enter { animation: feedin .35s ease-out both; }
  @keyframes feedin { from { transform: translateY(-6px); opacity: 0; } to { transform: none; opacity: 1; } }
  .feed .mark { width: 10px; height: 10px; margin-top: 4px; }
  .feed .mark.haiku { background: var(--haiku); border-radius: 50%; }
  .feed .mark.sonnet { background: var(--sonnet); }
  .feed .mark.opus { background: var(--opus); transform: rotate(45deg) scale(.85); }
  .feed .mark.unknown { border: 1px solid var(--unknown); border-radius: 50%; }
  .feed .what { font-size: 12px; }
  .feed .what b { font-weight: 600; }
  .feed .what small { display: block; font-family: var(--mono); font-size: 11px; color: var(--muted); }
  .feed .tok { font-family: var(--mono); font-size: 11px; color: var(--muted); text-align: right; }
  .v { display: inline-block; font-family: var(--mono); font-size: 10px; padding: 1px 6px; border-radius: 3px; border: 1px solid; margin-left: 6px; vertical-align: 1px; }
  .v.confirmed { color: var(--ok); border-color: var(--ok); }
  .v.refuted { color: var(--bad); border-color: var(--bad); }
  .v.inconclusive { color: var(--muted); border-color: var(--muted); border-style: dashed; }
  .v.running { color: var(--muted); border-color: var(--muted); border-style: dashed; }

  /* second row */
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: var(--gap); }
  .cost { padding: 14px 16px 16px; }
  .bar { display: flex; height: 26px; border-radius: 4px; overflow: hidden; background: var(--panel-2); border: 1px solid var(--line-soft); }
  .bar div { transition: width .6s cubic-bezier(.2,.8,.2,1); }
  .bar .h { background: var(--haiku); } .bar .s { background: var(--sonnet); } .bar .o { background: var(--opus); } .bar .u { background: var(--unknown); }
  .cost table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }
  .cost td { padding: 5px 0; border-bottom: 1px solid var(--line-soft); }
  .cost td:not(:first-child) { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }
  .cost tfoot td { border: 0; color: var(--muted); font-size: 11px; padding-top: 8px; }
  .funnel { padding: 14px 16px 16px; display: grid; gap: 8px; }
  .step { display: grid; grid-template-columns: 150px 1fr 60px; align-items: center; gap: 10px; font-size: 12px; }
  .step .track { height: 18px; background: var(--panel-2); border: 1px solid var(--line-soft); border-radius: 3px; overflow: hidden; }
  .step .fill { height: 100%; transition: width .6s cubic-bezier(.2,.8,.2,1); background: var(--sonnet); }
  .step.ok .fill { background: var(--ok); } .step.bad .fill { background: var(--bad); } .step.warn .fill { background: var(--warn); } .step.opus .fill { background: var(--opus); }
  .step .n { text-align: right; font-family: var(--mono); }

  /* table */
  table.runs { width: 100%; border-collapse: collapse; font-size: 12px; }
  table.runs th { text-align: left; font: 600 10px var(--display); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 10px 12px; border-bottom: 1px solid var(--line-soft); }
  table.runs td { padding: 9px 12px; border-bottom: 1px solid var(--line-soft); vertical-align: middle; }
  table.runs td.mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
  table.runs tr.row:hover { background: var(--panel-2); }
  .tier { display: inline-flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 11px; }
  .tier i { width: 9px; height: 9px; display: inline-block; }
  .tier.haiku i { background: var(--haiku); border-radius: 50%; }
  .tier.sonnet i { background: var(--sonnet); }
  .tier.opus i { background: var(--opus); transform: rotate(45deg) scale(.85); }
  .tier.unknown i { border: 1px solid var(--unknown); border-radius: 50%; background: transparent; }
  .lbl-btns { display: inline-flex; gap: 4px; }
  .lbl-btns button { font: 11px var(--mono); padding: 2px 7px; border-radius: 3px; border: 1px solid var(--line); background: transparent; color: var(--muted); cursor: pointer; }
  .lbl-btns button.on.tp { color: var(--ok); border-color: var(--ok); }
  .lbl-btns button.on.fp { color: var(--bad); border-color: var(--bad); }
  .lbl-btns button:hover { color: var(--text); }
  .foot { font-family: var(--mono); font-size: 11px; color: var(--dim); text-align: center; }
  .empty-inline { color: var(--muted); padding: 48px 12px; text-align: center; font-size: 13px; }

  @media (max-width: 1100px) { .kpis { grid-template-columns: repeat(3, 1fr); } .hero, .row2 { grid-template-columns: 1fr; } }
  @media (prefers-reduced-motion: reduce) { .pulse, .dot.enter, .dot.running, .feed li.enter { animation: none !important; } .bar div, .step .fill { transition: none !important; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand"><h1>Tierwork</h1><span>mission control</span></div>
    <div class="status"><span class="pulse" id="pulse"></span><span class="status-col"><span id="live-lbl">LIVE · SSE</span><span class="inflight" id="inflight">in flight: 0</span></span><span>·</span><span id="last-ev">last event —</span></div>
    <div class="spacer"></div>
    <div class="seg" id="window-seg">
      <button type="button" data-w="24h" class="on">24h</button>
      <button type="button" data-w="7d">7d</button>
      <button type="button" data-w="all">all</button>
    </div>
    <button class="btn" id="pause" type="button">Pause</button>
    <a class="dl" href="/api/export.json">Export JSON</a>
    <a class="dl" href="/api/export.csv">Export CSV</a>
  </div>
  <div class="status" id="sources" style="padding: 2px 0 0;"></div>

  <section class="kpis" id="kpis"></section>

  <section class="hero">
    <div class="panel">
      <header><h2>Review swimlanes</h2><span class="meta">one mark per sub-agent · size = output tokens</span><span class="spacer"></span>
        <div class="legend"><span class="haiku"><i></i>haiku</span><span class="sonnet"><i></i>sonnet</span><span class="opus"><i></i>opus</span><span class="unknown"><i></i>unknown</span></div></header>
      <div class="lanes" style="position:relative"><svg id="lanes" viewBox="0 0 1040 300" role="img" aria-label="Timeline of sub-agent runs by lane"></svg><div class="tip" id="tip" hidden></div><div id="lanes-empty" hidden></div></div>
    </div>
    <div class="panel feed">
      <header><h2>Live feed</h2><span class="spacer"></span><span class="meta" id="feed-n">0 events</span></header>
      <ol id="feed"></ol>
    </div>
  </section>

  <section class="row2">
    <div class="panel"><header><h2>Output tokens by tier</h2><span class="meta">est. cost at list price</span></header>
      <div class="cost"><div class="bar" id="bar"><div class="h"></div><div class="s"></div><div class="o"></div><div class="u"></div></div>
        <table><thead></thead><tbody id="cost-rows"></tbody><tfoot><tr><td colspan="4">haiku $5 · sonnet $10 · opus $25 per 1M output tokens (list price, not spend). Subscription plans meter differently.</td></tr></tfoot></table></div>
    </div>
    <div class="panel"><header><h2>Verdict funnel</h2><span class="meta">hunters → validators → primary → labels</span></header>
      <div class="funnel" id="funnel"></div>
    </div>
  </section>

  <section class="panel">
    <header><h2>Runs</h2><span class="meta">newest first</span></header>
    <div style="overflow-x:auto"><table class="runs"><thead><tr><th>time</th><th>agent</th><th>tier</th><th>msgs</th><th>tools</th><th>out tok</th><th>verdict</th><th>conf</th><th>primary?</th><th>task</th><th>label</th></tr></thead><tbody id="runs"></tbody></table></div>
  </section>
  <div class="foot">Local, read-only view of tierwork's SubagentStop log (+ optional labels file). No data leaves this machine.</div>
</div>

<script>
(function () {
  "use strict";
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var LANES = ["tierwork:gate", "tierwork:bug-hunter", "tierwork:bug-validator", "tierwork:compliance-reviewer"];
  var LANE_SHORT = { "tierwork:gate": "gate", "tierwork:bug-hunter": "bug-hunter", "tierwork:bug-validator": "bug-validator", "tierwork:compliance-reviewer": "compliance" };
  var PRICE = { haiku: 5, sonnet: 10, opus: 25 };

  // state.byKey: Map key -> row, used for de-dup/upsert of both the initial
  // /api/rows fetch and incoming SSE `rows` events.
  var state = { byKey: new Map(), window: "24h", paused: false, bufferedKeys: [] };

  function rowKey(r) { return (r.session_id || "") + " " + (r.agent_id || ""); }
  function num(v) {
    if (typeof v === "number" && !isNaN(v)) return v;
    if (typeof v === "string") { var n = parseFloat(v); if (!isNaN(n)) return n; }
    return 0;
  }
  function fmt(n) { return Math.round(n).toLocaleString("en-US"); }
  function $(s) { return document.querySelector(s); }
  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Tier: prefer spawn_model, then models[0], substring match on
  // haiku/sonnet/opus (case-insensitive); else "unknown".
  function tierOf(row) {
    var spawn = String(row.spawn_model || "").toLowerCase();
    if (spawn.indexOf("haiku") !== -1) return "haiku";
    if (spawn.indexOf("sonnet") !== -1) return "sonnet";
    if (spawn.indexOf("opus") !== -1) return "opus";
    var models = Array.isArray(row.models) ? row.models : [];
    var first = models.length ? String(models[0]).toLowerCase() : "";
    if (first.indexOf("haiku") !== -1) return "haiku";
    if (first.indexOf("sonnet") !== -1) return "sonnet";
    if (first.indexOf("opus") !== -1) return "opus";
    return "unknown";
  }

  function laneOf(row) {
    var t = row.agent_type;
    if (LANES.indexOf(t) !== -1) return t;
    if (t && String(t).indexOf("tierwork:") === 0) return "other";
    return "other";
  }

  function isPrimary(row) {
    return String(row.needs_primary_review || "").trim().toLowerCase() === "yes";
  }

  function tsMillis(row) {
    var t = row.ts ? Date.parse(row.ts) : NaN;
    return isNaN(t) ? null : t;
  }

  // Win-tier for the merge rule, mirroring bench/dashboard.py's
  // dedup_rows/_status_rank: a "done" row (or a legacy row with no `status`
  // field at all, since it predates the SubagentStart hook) always beats a
  // "running" row for the same key.
  function statusRank(row) {
    var s = row.status;
    if (s === undefined || s === null || s === "done") return 1;
    if (s === "running") return 0;
    return 1;
  }
  function isRunningRow(row) { return statusRank(row) === 0; }
  function isDoneRow(row) { return statusRank(row) === 1; }

  function upsertRows(list) {
    var added = [];
    list.forEach(function (r) {
      var k = rowKey(r);
      var existing = state.byKey.get(k);
      if (!existing) {
        state.byKey.set(k, r);
        added.push(k);
        return;
      }
      var newRank = statusRank(r), curRank = statusRank(existing);
      var take;
      if (newRank !== curRank) {
        take = newRank > curRank;
      } else {
        var nt = tsMillis(r), ct = tsMillis(existing);
        if (nt === null && ct === null) take = true;
        else if (nt === null) take = false;
        else if (ct === null) take = true;
        else take = nt >= ct;
      }
      if (take) {
        state.byKey.set(k, r);
        // A running row upgraded to done in place: replay the "just
        // arrived" enter animation as if it were newly added.
        if (newRank > curRank) added.push(k);
      }
    });
    return added;
  }

  function allRows() { return Array.from(state.byKey.values()); }

  function windowRows() {
    var rows = allRows();
    if (state.window === "all") return rows;
    var spanMs = state.window === "24h" ? 24 * 3600e3 : 7 * 24 * 3600e3;
    var cutoff = Date.now() - spanMs;
    return rows.filter(function (r) { var t = tsMillis(r); return t !== null && t >= cutoff; });
  }

  function tickIntervalMs(minT, maxT) {
    if (state.window === "24h") return 4 * 3600e3;
    if (state.window === "7d") return 24 * 3600e3;
    var span = Math.max(maxT - minT, 1);
    var raw = span / 6;
    // round to a friendly unit: hour/day/week granularity
    var units = [3600e3, 6 * 3600e3, 12 * 3600e3, 24 * 3600e3, 7 * 24 * 3600e3];
    for (var i = 0; i < units.length; i++) if (raw <= units[i]) return units[i];
    return units[units.length - 1];
  }

  // ---- KPIs ----
  function renderKPIs() {
    var rows = windowRows();
    var vals = rows.filter(function (r) { return r.agent_type === "tierwork:bug-validator"; });
    var conf = vals.filter(function (r) { return r.verdict === "confirmed"; }).length;
    var prim = vals.filter(isPrimary).length;
    var tok = rows.reduce(function (a, r) { return a + num(r.output_tokens); }, 0);
    var cost = rows.reduce(function (a, r) { var t = tierOf(r); return a + (PRICE[t] ? num(r.output_tokens) / 1e6 * PRICE[t] : 0); }, 0);
    var labeled = vals.filter(function (r) { return !!r.label; }).length;
    var opusTok = rows.filter(function (r) { return tierOf(r) === "opus"; }).reduce(function (a, r) { return a + num(r.output_tokens); }, 0);

    var doneRows = rows.filter(isDoneRow);
    var k = [
      ["Sub-agent runs", doneRows.length ? fmt(doneRows.length) : "—"],
      ["Validators confirmed", vals.length ? Math.round(conf / vals.length * 100) + "%" : "—", vals.length ? conf + " of " + vals.length : ""],
      ["Needs primary review", vals.length ? Math.round(prim / vals.length * 100) + "%" : "—", vals.length ? prim + " findings" : ""],
      ["Output tokens", rows.length ? fmt(tok) : "—", "all tiers"],
      ["Est. cost", rows.length ? "$" + cost.toFixed(2) : "—", tok ? "opus share " + Math.round(opusTok / tok * 100) + "%" : ""],
      ["Labeled", vals.length ? Math.round(labeled / vals.length * 100) + "%" : "—", vals.length ? labeled + " of " + vals.length + " validators" : ""]
    ];
    $("#kpis").innerHTML = k.map(function (x, i) {
      return '<div class="kpi' + (i === 4 ? " hero" : "") + '"><div class="lbl">' + esc(x[0]) + '</div><div class="val num">' + esc(x[1]) + '</div><div class="sub">' + esc(x[2] || "") + "</div></div>";
    }).join("");
  }

  // ---- Swimlanes ----
  var svg = $("#lanes"), NS = "http://www.w3.org/2000/svg";
  var tip = $("#tip");
  function el(n, a) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); return e; }

  function renderLanes(newKeys) {
    var rows = windowRows().filter(function (r) { return tsMillis(r) !== null; });
    var lanesEmpty = $("#lanes-empty");
    svg.innerHTML = "";
    if (!rows.length) {
      svg.style.display = "none";
      lanesEmpty.hidden = false;
      lanesEmpty.className = "empty-inline";
      lanesEmpty.textContent = "No runs yet. Records appear here as soon as a tierwork:* sub-agent finishes.";
      return;
    }
    svg.style.display = "";
    lanesEmpty.hidden = true;

    var lanes = LANES.slice();
    var hasOther = rows.some(function (r) { return laneOf(r) === "other"; });
    if (hasOther) lanes.push("other");
    var laneShort = lanes.map(function (l) { return l === "other" ? "other" : LANE_SHORT[l]; });

    var L = 120, R = 1030, T = 18, LH = 300 / lanes.length, W = R - L;
    // Axis follows the selected window (not the data extent) so ticks are
    // stable and "now" sits at the right edge; "all" pads the data range.
    var nowT = Date.now();
    var minT, maxT;
    if (state.window === "24h") { minT = nowT - 24 * 3600e3; maxT = nowT; }
    else if (state.window === "7d") { minT = nowT - 7 * 24 * 3600e3; maxT = nowT; }
    else {
      minT = Math.min.apply(null, rows.map(function (r) { return tsMillis(r); }));
      maxT = nowT;
      if (!(maxT - minT > 3600e3)) minT = maxT - 3600e3;
    }
    var span = Math.max(maxT - minT, 1);
    svg.setAttribute("viewBox", "0 0 1040 " + (T + lanes.length * LH + 24));
    svg.setAttribute("height", (T + lanes.length * LH + 24));

    lanes.forEach(function (ln, i) {
      var y = T + i * LH + LH / 2;
      svg.appendChild(el("line", { x1: L, x2: R, y1: y, y2: y, class: "grid-l" }));
      var t = el("text", { x: 8, y: y + 4, class: "lane-lbl" });
      t.textContent = laneShort[i];
      svg.appendChild(t);
    });

    var tick = tickIntervalMs(minT, maxT);
    var axisY = T + lanes.length * LH + 6;
    // Ticks count back from "now" so the last tick is always the right edge.
    var nTicks = Math.floor(span / tick);
    for (var k = nTicks; k >= 0; k--) {
      var tt = maxT - k * tick;
      var x = L + W * (tt - minT) / span;
      var d = new Date(tt);
      var label = el("text", { x: x, y: axisY, class: "axis-t", "text-anchor": k === 0 ? "end" : (k === nTicks ? "start" : "middle") });
      if (k === 0) label.textContent = "now";
      else if (state.window === "24h") label.textContent = "-" + Math.round(k * tick / 3600e3) + "h";
      else if (state.window === "7d") label.textContent = "-" + Math.round(k * tick / 86400e3) + "d";
      else label.textContent = d.toLocaleDateString([], { month: "short", day: "numeric" });
      svg.appendChild(label);
    }

    var newKeySet = new Set(newKeys || []);
    var byTs = rows.slice().sort(function (a, b) { return tsMillis(a) - tsMillis(b); });
    byTs.forEach(function (r) {
      var lane = laneOf(r);
      var li = lanes.indexOf(lane);
      if (li === -1) return;
      var x = L + W * (tsMillis(r) - minT) / span;
      var y = T + li * LH + LH / 2;
      var tier = tierOf(r);
      var rad = 4 + Math.sqrt(Math.max(num(r.output_tokens), 0)) / 9;
      var col = "var(--" + tier + ")";
      var s;
      if (tier === "unknown") {
        s = el("circle", { cx: x, cy: y, r: rad, fill: "none", stroke: col, "stroke-width": 1.5 });
      } else if (tier === "haiku") {
        s = el("circle", { cx: x, cy: y, r: rad, fill: col });
      } else if (tier === "sonnet") {
        s = el("rect", { x: x - rad, y: y - rad, width: rad * 2, height: rad * 2, fill: col });
      } else {
        s = el("polygon", { points: x + "," + (y - rad) + " " + (x + rad) + "," + y + " " + x + "," + (y + rad) + " " + (x - rad) + "," + y, fill: col });
      }
      if (r.verdict === "refuted") { s.setAttribute("stroke", "var(--bad)"); s.setAttribute("stroke-width", "2"); s.setAttribute("fill-opacity", ".35"); }
      if (r.verdict === "inconclusive") { s.setAttribute("stroke-dasharray", "2 2"); s.setAttribute("stroke", col); s.setAttribute("fill-opacity", ".25"); }
      var running = isRunningRow(r);
      if (running) {
        // No end ts yet: render hollow (stroke only) at the start ts, with
        // a soft pulse (handled purely in CSS via transform/opacity).
        s.setAttribute("fill", col);
        s.setAttribute("fill-opacity", ".15");
        s.setAttribute("stroke", col);
        s.setAttribute("stroke-width", "1.5");
      }
      s.setAttribute("class", "dot" + (running ? " running" : "") + (newKeySet.has(rowKey(r)) && !reduce ? " enter" : ""));
      s.setAttribute("tabindex", "0");
      s.setAttribute("aria-label", (r.agent_type || "") + " " + tier + " " + fmt(num(r.output_tokens)) + " output tokens " + (running ? "running" : (r.verdict || "")));
      var show = function (ev) {
        tip.hidden = false;
        tip.innerHTML = running
          ? "<b>" + esc(r.agent_type) + "</b> · " + esc(tier) + "<br>" + esc(r.description || "") + '<br><span class="v running">running</span>'
          : "<b>" + esc(r.agent_type) + "</b> · " + esc(tier) + "<br>" + esc(r.description || "") + "<br>out " + fmt(num(r.output_tokens)) + " · msgs " + esc(r.msgs) + " · tools " + esc(r.tool_calls) + (r.verdict ? "<br>verdict " + esc(r.verdict) + (r.confidence !== undefined && r.confidence !== null ? " · conf " + esc(r.confidence) : "") : "");
        var b = svg.getBoundingClientRect();
        var pt = ev.clientX ? { x: ev.clientX - b.left, y: ev.clientY - b.top } : { x: x, y: y };
        tip.style.left = Math.min(pt.x + 12, b.width - 240) + "px";
        tip.style.top = (pt.y + 12) + "px";
      };
      s.addEventListener("mousemove", show);
      s.addEventListener("focus", show);
      s.addEventListener("mouseleave", function () { tip.hidden = true; });
      s.addEventListener("blur", function () { tip.hidden = true; });
      svg.appendChild(s);
    });
  }

  // ---- Feed ----
  function renderFeed(newKeys) {
    var feed = $("#feed");
    var rows = windowRows().filter(function (r) { return tsMillis(r) !== null; });
    var newKeySet = new Set(newKeys || []);
    var recent = rows.slice().sort(function (a, b) { return tsMillis(b) - tsMillis(a); }).slice(0, 14);
    feed.innerHTML = recent.map(function (r) {
      var tier = tierOf(r);
      var running = isRunningRow(r);
      var verdictHtml = running
        ? '<span class="v running">running</span>'
        : (r.verdict ? '<span class="v ' + esc(r.verdict) + '">' + esc(r.verdict) + (r.confidence !== undefined && r.confidence !== null ? " " + esc(r.confidence) : "") + "</span>" : "");
      var smallHtml = running
        ? esc(r.description || "") + ' · <span class="running-elapsed" data-start="' + tsMillis(r) + '">running · 0s</span>'
        : esc(r.description || "") + " · " + new Date(tsMillis(r)).toLocaleTimeString();
      var tokHtml = running ? "" : fmt(num(r.output_tokens)) + "<br>tok";
      return '<li' + (newKeySet.has(rowKey(r)) && !reduce ? ' class="enter"' : "") + '><span class="mark ' + tier + '"></span><span class="what"><b>' + esc((r.agent_type || "").replace("tierwork:", "")) + "</b>" + verdictHtml + "<small>" + smallHtml + "</small></span><span class=\"tok num\">" + tokHtml + "</span></li>";
    }).join("");
    updateRunningElapsed();
    $("#feed-n").textContent = rows.length + " events";
    var lastT = rows.length ? Math.max.apply(null, rows.map(function (r) { return tsMillis(r); })) : null;
    $("#last-ev").textContent = "last event " + (lastT ? new Date(lastT).toLocaleTimeString() : "—");
  }

  // ---- Running-row elapsed-time ticker (client-side only, no server poll) ----
  function updateRunningElapsed() {
    var now = Date.now();
    document.querySelectorAll(".running-elapsed").forEach(function (span) {
      var start = parseInt(span.getAttribute("data-start"), 10);
      if (isNaN(start)) return;
      var secs = Math.max(0, Math.round((now - start) / 1000));
      span.textContent = "running · " + secs + "s";
    });
  }
  setInterval(updateRunningElapsed, 1000);

  // ---- "in flight" indicator under the LIVE label ----
  function renderInFlight() {
    var n = allRows().filter(isRunningRow).length;
    $("#inflight").textContent = "in flight: " + n;
  }

  // ---- Cost bar ----
  function renderCost() {
    var rows = windowRows();
    var t = { haiku: 0, sonnet: 0, opus: 0, unknown: 0 }, n = { haiku: 0, sonnet: 0, opus: 0, unknown: 0 };
    rows.forEach(function (r) { var tier = tierOf(r); t[tier] += num(r.output_tokens); n[tier]++; });
    var tot = t.haiku + t.sonnet + t.opus + t.unknown || 1;
    var bar = $("#bar");
    bar.children[0].style.width = (t.haiku / tot * 100) + "%";
    bar.children[1].style.width = (t.sonnet / tot * 100) + "%";
    bar.children[2].style.width = (t.opus / tot * 100) + "%";
    bar.children[3].style.width = (t.unknown / tot * 100) + "%";
    $("#cost-rows").innerHTML = ["haiku", "sonnet", "opus", "unknown"].map(function (k) {
      var price = PRICE[k];
      var costStr = price ? "$" + (t[k] / 1e6 * price).toFixed(3) : "—";
      return '<tr><td><span class="tier ' + k + '"><i></i>' + k + "</span></td><td>" + n[k] + " runs</td><td>" + fmt(t[k]) + " tok</td><td>" + costStr + "</td></tr>";
    }).join("");
  }

  // ---- Verdict funnel ----
  function renderFunnel() {
    var rows = windowRows();
    var hunters = rows.filter(function (r) { return r.agent_type === "tierwork:bug-hunter"; }).length;
    var vals = rows.filter(function (r) { return r.agent_type === "tierwork:bug-validator"; });
    var c = vals.filter(function (r) { return r.verdict === "confirmed"; }).length;
    var rf = vals.filter(function (r) { return r.verdict === "refuted"; }).length;
    var inc = vals.filter(function (r) { return r.verdict === "inconclusive"; }).length;
    var prim = vals.filter(isPrimary).length;
    var tp = vals.filter(function (r) { return r.label === "true_positive"; }).length;
    var fp = vals.filter(function (r) { return r.label === "false_positive"; }).length;
    var max = Math.max(vals.length, 1);
    var steps = [
      ["Findings validated", vals.length, "", vals.length],
      ["Confirmed", c, "ok", c],
      ["Refuted", rf, "bad", rf],
      ["Inconclusive", inc, "warn", inc],
      ["Needs primary review", prim, "opus", prim],
      ["Labeled true positive", tp, "ok", tp],
      ["Labeled false positive", fp, "bad", fp]
    ];
    $("#funnel").innerHTML =
      '<div class="step"><span>Hunter runs</span><div class="track"><div class="fill" style="width:100%;background:var(--opus)"></div></div><span class="n">' + hunters + "</span></div>" +
      steps.map(function (s) {
        return '<div class="step ' + s[2] + '"><span>' + esc(s[0]) + '</span><div class="track"><div class="fill" style="width:' + (s[3] / max * 100) + '%"></div></div><span class="n">' + s[1] + "</span></div>";
      }).join("");
  }

  // ---- Runs table ----
  function labelButtonsHtml(r) {
    if (r.agent_type !== "tierwork:bug-validator") return "";
    return '<span class="lbl-btns" data-session="' + esc(r.session_id) + '" data-agent="' + esc(r.agent_id) + '">' +
      '<button class="tp' + (r.label === "true_positive" ? " on" : "") + '" data-l="true_positive" aria-label="label true positive">TP</button>' +
      '<button class="fp' + (r.label === "false_positive" ? " on" : "") + '" data-l="false_positive" aria-label="label false positive">FP</button>' +
      "</span>";
  }

  function renderRuns() {
    var rows = windowRows().filter(function (r) { return tsMillis(r) !== null; });
    var tb = $("#runs");
    var sorted = rows.slice().sort(function (a, b) { return tsMillis(b) - tsMillis(a); }).slice(0, 200);
    tb.innerHTML = sorted.map(function (r) {
      var tier = tierOf(r);
      var running = isRunningRow(r);
      var verdictCell = running
        ? '<span class="v running">running</span>'
        : (r.verdict ? '<span class="v ' + esc(r.verdict) + '">' + esc(r.verdict) + "</span>" : "—");
      return "<tr class=\"row\">" +
        '<td class="mono">' + new Date(tsMillis(r)).toLocaleTimeString() + "</td>" +
        "<td>" + esc((r.agent_type || "").replace("tierwork:", "")) + "</td>" +
        '<td><span class="tier ' + tier + '"><i></i>' + tier + "</span></td>" +
        '<td class="mono">' + esc(r.msgs) + "</td>" +
        '<td class="mono">' + esc(r.tool_calls) + "</td>" +
        '<td class="mono">' + fmt(num(r.output_tokens)) + "</td>" +
        "<td>" + verdictCell + "</td>" +
        '<td class="mono">' + (r.confidence !== undefined && r.confidence !== null && r.confidence !== "" ? esc(r.confidence) : "—") + "</td>" +
        "<td>" + (r.verdict ? (isPrimary(r) ? '<span style="color:var(--warn)">yes</span>' : "no") : "—") + "</td>" +
        "<td>" + esc(r.description || "") + "</td>" +
        "<td>" + labelButtonsHtml(r) + "</td>" +
        "</tr>";
    }).join("");

    tb.querySelectorAll(".lbl-btns button").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var wrap = btn.closest(".lbl-btns");
        var sessionId = wrap.getAttribute("data-session");
        var agentId = wrap.getAttribute("data-agent");
        var label = btn.getAttribute("data-l");
        fetch("/api/label", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, agent_id: agentId, label: label, note: "" })
        })
          .then(function (resp) { if (!resp.ok) throw new Error("HTTP " + resp.status); return resp.json(); })
          .then(function (rec) {
            var k = (sessionId || "") + " " + (agentId || "");
            var row = state.byKey.get(k);
            if (row) { row.label = rec.label; row.label_note = rec.note; row.label_ts = rec.label_ts; }
            renderAll();
          })
          .catch(function () { /* leave UI as-is; user can retry */ });
      });
    });
  }

  function renderSources() {
    var sources = [];
    allRows().forEach(function (r) { if (r.source && sources.indexOf(r.source) === -1) sources.push(r.source); });
    sources.sort();
    $("#sources").textContent = sources.length ? "src: " + sources.join(", ") : "src: (no data loaded)";
  }

  function renderAll(newKeys) {
    renderKPIs();
    renderLanes(newKeys);
    renderFeed(newKeys);
    renderCost();
    renderFunnel();
    renderRuns();
    renderSources();
    renderInFlight();
  }

  // ---- time window control ----
  document.querySelectorAll("#window-seg button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#window-seg button").forEach(function (b) { b.classList.remove("on"); });
      btn.classList.add("on");
      state.window = btn.getAttribute("data-w");
      renderAll();
    });
  });

  // ---- pause / resume ----
  var pauseBtn = $("#pause");
  pauseBtn.addEventListener("click", function () {
    state.paused = !state.paused;
    pauseBtn.textContent = state.paused ? "Resume" : "Pause";
    $("#pulse").classList.toggle("stale", state.paused);
    if (!state.paused && state.bufferedKeys.length) {
      var keys = state.bufferedKeys;
      state.bufferedKeys = [];
      renderAll(keys);
    } else if (!state.paused) {
      renderAll();
    }
  });

  // ---- initial load ----
  function loadAndRender() {
    return fetch("/api/rows")
      .then(function (resp) { if (!resp.ok) throw new Error("HTTP " + resp.status); return resp.json(); })
      .then(function (rows) {
        upsertRows(Array.isArray(rows) ? rows : []);
        renderAll();
      })
      .catch(function () {
        renderAll();
      });
  }
  loadAndRender();

  // ---- SSE with polling fallback ----
  var liveLbl = $("#live-lbl");
  var pulse = $("#pulse");
  var pollTimer = null;
  var es = null;

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function startPolling() {
    if (pollTimer) return;
    liveLbl.textContent = "POLLING";
    pulse.classList.add("stale");
    pollTimer = setInterval(function () {
      fetch("/api/rows")
        .then(function (resp) { if (!resp.ok) throw new Error("HTTP " + resp.status); return resp.json(); })
        .then(function (rows) {
          var added = upsertRows(Array.isArray(rows) ? rows : []);
          if (state.paused) {
            state.bufferedKeys = state.bufferedKeys.concat(added);
          } else {
            renderAll(added);
          }
        })
        .catch(function () {});
    }, 10000);
  }

  function connectSSE() {
    try {
      es = new EventSource("/api/events");
    } catch (e) {
      startPolling();
      return;
    }
    es.addEventListener("hello", function () {
      stopPolling();
      liveLbl.textContent = state.paused ? "PAUSED" : "LIVE · SSE";
      pulse.classList.toggle("stale", state.paused);
    });
    es.addEventListener("rows", function (ev) {
      var newRows;
      try { newRows = JSON.parse(ev.data); } catch (e) { return; }
      if (!Array.isArray(newRows) || !newRows.length) return;
      var added = upsertRows(newRows);
      if (state.paused) {
        state.bufferedKeys = state.bufferedKeys.concat(added);
      } else {
        renderAll(added);
      }
    });
    es.onopen = function () {
      stopPolling();
      liveLbl.textContent = state.paused ? "PAUSED" : "LIVE · SSE";
      pulse.classList.toggle("stale", state.paused);
    };
    es.onerror = function () {
      startPolling();
    };
  }
  connectSSE();
})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--log",
        action="append",
        default=None,
        help="path to a reviews.jsonl file, or a directory of *.jsonl files "
        "(non-recursive). May be given multiple times; defaults to "
        "TIERWORK_LOG or ~/.tierwork/reviews.jsonl",
    )
    ap.add_argument("--labels", default="~/.tierwork/labels.jsonl", help="path to labels.jsonl")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    log_arg_paths = args.log or [default_log_path()]
    log_paths = [Path(os.path.expanduser(str(p))) for p in log_arg_paths]
    labels_path = Path(os.path.expanduser(args.labels))

    tailer = LogTailer(log_paths, labels_path)
    tailer.start()

    handler = make_handler(log_paths, labels_path, tailer)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving at http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
