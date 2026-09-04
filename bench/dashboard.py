#!/usr/bin/env python3
"""Local review dashboard for tierwork's SubagentStop log.

Usage:
    bench/dashboard.py [--log ~/.tierwork/reviews.jsonl]
                        [--labels ~/.tierwork/labels.jsonl]
                        [--port 8765]

Serves a single self-contained HTML page (stdlib http.server only, no
third-party deps, no CDN or other external network calls) with stat tiles,
two hand-built inline-SVG charts, and a sortable table of every logged
tierwork sub-agent run. Binds to 127.0.0.1 only.

Routes:
    GET  /            the dashboard page
    GET  /api/rows    JSON array: log rows merged with the latest label
                       (by session_id+agent_id) from the labels file
    POST /api/label   body {"session_id", "agent_id", "label", "note"};
                       appends one JSON line to the labels file

Field names, verdict values, and the needs_primary_review convention
("yes"/other, case-insensitive string) are read the same way bench/report.py
reads them, so shares shown here match report.py's numbers on the same log.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VALID_LABELS = {"true_positive", "false_positive", "unclear"}


def default_log_path():
    env = os.environ.get("TIERWORK_LOG")
    if env:
        return env
    return "~/.tierwork/reviews.jsonl"


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


def merged_rows(log_path: Path, labels_path: Path):
    rows = load_jsonl(log_path)
    labels = load_labels(labels_path)
    out = []
    for r in rows:
        row = dict(r)
        key = (row.get("session_id"), row.get("agent_id"))
        lab = labels.get(key)
        if lab:
            row["label"] = lab.get("label")
            row["note"] = lab.get("note")
            row["label_ts"] = lab.get("label_ts")
        else:
            row["label"] = None
            row["note"] = None
            row["label_ts"] = None
        out.append(row)
    return out


def make_handler(log_path: Path, labels_path: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TierworkDashboard/1"

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

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/?"):
                self._send_html(PAGE_HTML)
            elif self.path == "/api/rows" or self.path.startswith("/api/rows?"):
                try:
                    rows = merged_rows(log_path, labels_path)
                    self._send_json(rows)
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
<title>tierwork review dashboard</title>
<style>
  :root {
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --grid:           #e1e0d9;
    --baseline:       #c3c2b7;
    --border:         rgba(11,11,11,0.10);
    --series-haiku:   #1baf7a; /* aqua */
    --series-sonnet:  #2a78d6; /* blue */
    --series-opus:    #4a3aa7; /* violet */
    --series-other:   #898781;
    --line-1:         #2a78d6; /* blue */
    --line-2:         #eb6834; /* orange */
    --line-3:         #1baf7a; /* aqua */
    --line-4:         #eda100; /* yellow */
    --line-5:         #e87ba4; /* magenta */
    --line-6:         #008300; /* green */
    --line-7:         #4a3aa7; /* violet */
    --line-8:         #e34948; /* red */
    --good:           #0ca30c;
    --warning:        #fab219;
    --critical:       #d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --grid:           #2c2c2a;
      --baseline:       #383835;
      --border:         rgba(255,255,255,0.10);
      --series-haiku:   #199e70;
      --series-sonnet:  #3987e5;
      --series-opus:    #9085e9;
      --series-other:   #898781;
      --line-1:         #3987e5;
      --line-2:         #d95926;
      --line-3:         #199e70;
      --line-4:         #c98500;
      --line-5:         #d55181;
      --line-6:         #008300;
      --line-7:         #9085e9;
      --line-8:         #e66767;
      --good:           #0ca30c;
      --warning:        #fab219;
      --critical:       #e66767;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --grid:           #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
    --series-haiku:   #199e70;
    --series-sonnet:  #3987e5;
    --series-opus:    #9085e9;
    --series-other:   #898781;
    --line-1:         #3987e5;
    --line-2:         #d95926;
    --line-3:         #199e70;
    --line-4:         #c98500;
    --line-5:         #d55181;
    --line-6:         #008300;
    --line-7:         #9085e9;
    --line-8:         #e66767;
    --good:           #0ca30c;
    --warning:        #fab219;
    --critical:       #e66767;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--page);
    color: var(--text-primary);
    font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 24px;
  }
  h1 { font-size: 18px; margin: 0 0 4px; }
  h2 { font-size: 14px; margin: 0 0 12px; color: var(--text-secondary); }
  .sub { color: var(--text-secondary); margin: 0 0 20px; }
  .toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
  button {
    font: inherit;
    background: var(--surface-1);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 12px;
    cursor: pointer;
  }
  button:hover { border-color: var(--text-secondary); }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }
  .tile {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
  }
  .tile .value {
    font-size: 24px;
    font-variant-numeric: proportional-nums;
    font-weight: 600;
  }
  .tile .label { color: var(--text-secondary); font-size: 12px; margin-top: 2px; }
  .panel {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 24px;
    overflow-x: auto;
  }
  .empty {
    color: var(--text-secondary);
    padding: 40px 0;
    text-align: center;
  }
  svg text { fill: var(--text-secondary); font-size: 11px; }
  svg .axis-label { fill: var(--text-muted); }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 8px; font-size: 12px; color: var(--text-secondary); }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
  table { border-collapse: collapse; width: 100%; font-size: 12px; }
  th, td {
    text-align: left;
    padding: 6px 8px;
    border-bottom: 1px solid var(--grid);
    white-space: nowrap;
  }
  th { color: var(--text-secondary); font-weight: 600; position: sticky; top: 0; background: var(--surface-1); }
  td.desc { white-space: normal; max-width: 320px; }
  .label-controls { display: flex; gap: 4px; align-items: center; }
  .label-controls button { padding: 3px 8px; font-size: 11px; }
  .label-controls input[type=text] { font: inherit; font-size: 11px; width: 90px; padding: 3px 6px; border-radius: 4px; border: 1px solid var(--border); background: var(--page); color: var(--text-primary); }
  .label-tag { font-size: 11px; padding: 2px 6px; border-radius: 10px; border: 1px solid var(--border); }
  .label-tag.true_positive { color: var(--good); border-color: var(--good); }
  .label-tag.false_positive { color: var(--critical); border-color: var(--critical); }
  .label-tag.unclear { color: var(--warning); border-color: var(--warning); }
</style>
</head>
<body>
  <h1>tierwork review dashboard</h1>
  <p class="sub">Local, read-only view of <code>~/.tierwork/reviews.jsonl</code> (+ optional labels file). No data leaves this machine.</p>
  <div class="toolbar">
    <button id="reload-btn" type="button">Reload</button>
    <span id="status" style="color: var(--text-secondary);"></span>
  </div>

  <div id="tiles" class="tiles"></div>

  <div class="panel">
    <h2>Output tokens by agent type</h2>
    <div id="bar-chart"></div>
  </div>

  <div class="panel">
    <h2>Output tokens per run over time</h2>
    <div id="line-chart"></div>
  </div>

  <div class="panel">
    <h2>Runs</h2>
    <div id="table-wrap"></div>
  </div>

<script>
(function () {
  "use strict";

  var state = { rows: [] };

  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function num(v) {
    if (typeof v === "number" && !isNaN(v)) return v;
    if (typeof v === "string") {
      var n = parseFloat(v);
      if (!isNaN(n)) return n;
    }
    return 0;
  }

  function basename(p) {
    if (!p) return "";
    var parts = String(p).split("/").filter(Boolean);
    return parts.length ? parts[parts.length - 1] : String(p);
  }

  // Bucket the first entry of a row's `models` list into haiku/sonnet/opus/other,
  // matching the naming already used elsewhere in bench/ (model id strings
  // contain "haiku"/"sonnet"/"opus").
  function modelBucket(row) {
    var models = Array.isArray(row.models) ? row.models : [];
    var first = models.length ? String(models[0]).toLowerCase() : "";
    if (first.indexOf("haiku") !== -1) return "haiku";
    if (first.indexOf("sonnet") !== -1) return "sonnet";
    if (first.indexOf("opus") !== -1) return "opus";
    return "other";
  }

  var bucketColorVar = {
    haiku: "--series-haiku",
    sonnet: "--series-sonnet",
    opus: "--series-opus",
    other: "--series-other"
  };

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // Fixed line-chart palette slots, assigned per distinct agent_type in
  // first-seen order (categorical hues in fixed order, per dataviz skill).
  var lineSlots = ["--line-1", "--line-2", "--line-3", "--line-4", "--line-5", "--line-6", "--line-7", "--line-8"];

  function computeStats(rows) {
    var total = rows.length;
    var validators = rows.filter(function (r) { return r.agent_type === "tierwork:bug-validator"; });
    var confirmed = validators.filter(function (r) { return r.verdict === "confirmed"; }).length;
    var needsReview = validators.filter(function (r) {
      return String(r.needs_primary_review || "").trim().toLowerCase() === "yes";
    }).length;
    var totalOutputTokens = rows.reduce(function (sum, r) { return sum + num(r.output_tokens); }, 0);
    var labeled = validators.filter(function (r) { return !!r.label; }).length;

    return {
      total: total,
      validatorCount: validators.length,
      confirmedShare: validators.length ? confirmed / validators.length : null,
      needsReviewShare: validators.length ? needsReview / validators.length : null,
      totalOutputTokens: totalOutputTokens,
      labeledShare: validators.length ? labeled / validators.length : null
    };
  }

  function pct(x) {
    if (x === null || x === undefined) return "n/a";
    return (x * 100).toFixed(0) + "%";
  }

  function renderTiles(stats) {
    var tiles = [
      { label: "Total sub-agent runs", value: stats.total },
      { label: "Validator runs", value: stats.validatorCount },
      { label: "Confirmed share (validators)", value: pct(stats.confirmedShare) },
      { label: "needs_primary_review share", value: pct(stats.needsReviewShare) },
      { label: "Total output tokens", value: stats.totalOutputTokens.toLocaleString() },
      { label: "Labeled share (validators)", value: pct(stats.labeledShare) }
    ];
    var el = document.getElementById("tiles");
    el.innerHTML = tiles.map(function (t) {
      return '<div class="tile"><div class="value">' + esc(t.value) + '</div><div class="label">' + esc(t.label) + "</div></div>";
    }).join("");
  }

  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function renderBarChart(rows) {
    var host = document.getElementById("bar-chart");
    host.innerHTML = "";
    if (!rows.length) {
      host.innerHTML = '<div class="empty">No data yet.</div>';
      return;
    }

    var byType = {};
    rows.forEach(function (r) {
      var t = r.agent_type || "(unknown)";
      if (!byType[t]) byType[t] = { total: 0, bucket: modelBucket(r) };
      byType[t].total += num(r.output_tokens);
    });
    var types = Object.keys(byType).sort();
    if (!types.length) {
      host.innerHTML = '<div class="empty">No data yet.</div>';
      return;
    }

    var width = Math.max(480, types.length * 90 + 80);
    var height = 240;
    var marginLeft = 60, marginBottom = 60, marginTop = 16, marginRight = 16;
    var plotW = width - marginLeft - marginRight;
    var plotH = height - marginTop - marginBottom;
    var maxVal = Math.max.apply(null, types.map(function (t) { return byType[t].total; })) || 1;

    var svg = svgEl("svg", {
      viewBox: "0 0 " + width + " " + height,
      width: "100%",
      height: height,
      role: "img",
      "aria-label": "Bar chart of total output tokens per agent type"
    });
    var title = svgEl("title", {});
    title.textContent = "Output tokens summed per agent type, colored by dominant model tier";
    svg.appendChild(title);

    // y axis gridlines + ticks
    var ticks = 4;
    for (var i = 0; i <= ticks; i++) {
      var yv = maxVal * i / ticks;
      var y = marginTop + plotH - (plotH * i / ticks);
      var grid = svgEl("line", { x1: marginLeft, x2: width - marginRight, y1: y, y2: y, stroke: "var(--grid)", "stroke-width": 1 });
      svg.appendChild(grid);
      var label = svgEl("text", { x: marginLeft - 8, y: y + 4, "text-anchor": "end" });
      label.textContent = Math.round(yv).toLocaleString();
      svg.appendChild(label);
    }
    var axisLabel = svgEl("text", { x: 8, y: marginTop, class: "axis-label" });
    axisLabel.textContent = "output tokens";
    svg.appendChild(axisLabel);

    var barW = Math.min(60, plotW / types.length - 20);
    types.forEach(function (t, idx) {
      var slotW = plotW / types.length;
      var cx = marginLeft + slotW * idx + slotW / 2;
      var val = byType[t].total;
      var barH = maxVal ? (val / maxVal) * plotH : 0;
      var x = cx - barW / 2;
      var y = marginTop + plotH - barH;
      var colorVar = bucketColorVar[byType[t].bucket] || bucketColorVar.other;
      var color = cssVar(colorVar);

      var rect = svgEl("rect", {
        x: x, y: y, width: barW, height: Math.max(barH, 1),
        fill: color, rx: 4, ry: 4
      });
      var rtitle = svgEl("title", {});
      rtitle.textContent = t + ": " + val.toLocaleString() + " output tokens (" + byType[t].bucket + ")";
      rect.appendChild(rtitle);
      svg.appendChild(rect);

      var xlabel = svgEl("text", { x: cx, y: height - marginBottom + 18, "text-anchor": "middle" });
      xlabel.textContent = t.length > 20 ? t.slice(0, 18) + "…" : t;
      svg.appendChild(xlabel);
    });

    var baseline = svgEl("line", {
      x1: marginLeft, x2: width - marginRight, y1: marginTop + plotH, y2: marginTop + plotH,
      stroke: "var(--baseline)", "stroke-width": 1
    });
    svg.appendChild(baseline);

    host.appendChild(svg);

    var legend = document.createElement("div");
    legend.className = "legend";
    ["haiku", "sonnet", "opus", "other"].forEach(function (b) {
      var used = types.some(function (t) { return byType[t].bucket === b; });
      if (!used) return;
      var item = document.createElement("span");
      item.className = "legend-item";
      item.innerHTML = '<span class="swatch" style="background:' + cssVar(bucketColorVar[b]) + '"></span>' + esc(b);
      legend.appendChild(item);
    });
    host.appendChild(legend);
  }

  function renderLineChart(rows) {
    var host = document.getElementById("line-chart");
    host.innerHTML = "";
    var pts = rows
      .map(function (r) {
        var t = r.ts ? Date.parse(r.ts) : NaN;
        return { t: t, y: num(r.output_tokens), type: r.agent_type || "(unknown)" };
      })
      .filter(function (p) { return !isNaN(p.t); });

    if (!pts.length) {
      host.innerHTML = '<div class="empty">No data yet.</div>';
      return;
    }

    var types = [];
    pts.forEach(function (p) { if (types.indexOf(p.type) === -1) types.push(p.type); });
    types.sort();
    var colorOf = {};
    types.forEach(function (t, i) { colorOf[t] = cssVar(lineSlots[i % lineSlots.length]); });

    var width = 720, height = 260;
    var marginLeft = 70, marginBottom = 40, marginTop = 16, marginRight = 16;
    var plotW = width - marginLeft - marginRight;
    var plotH = height - marginTop - marginBottom;

    var minT = Math.min.apply(null, pts.map(function (p) { return p.t; }));
    var maxT = Math.max.apply(null, pts.map(function (p) { return p.t; }));
    var maxY = Math.max.apply(null, pts.map(function (p) { return p.y; })) || 1;
    var spanT = maxT - minT || 1;

    function xOf(t) { return marginLeft + ((t - minT) / spanT) * plotW; }
    function yOf(y) { return marginTop + plotH - (y / maxY) * plotH; }

    var svg = svgEl("svg", {
      viewBox: "0 0 " + width + " " + height,
      width: "100%",
      height: height,
      role: "img",
      "aria-label": "Line and dot chart of output tokens per run over time, colored by agent type"
    });
    var title = svgEl("title", {});
    title.textContent = "Output tokens per run over time, by agent type";
    svg.appendChild(title);

    var ticks = 4;
    for (var i = 0; i <= ticks; i++) {
      var yv = maxY * i / ticks;
      var y = yOf(yv);
      var grid = svgEl("line", { x1: marginLeft, x2: width - marginRight, y1: y, y2: y, stroke: "var(--grid)", "stroke-width": 1 });
      svg.appendChild(grid);
      var label = svgEl("text", { x: marginLeft - 8, y: y + 4, "text-anchor": "end" });
      label.textContent = Math.round(yv).toLocaleString();
      svg.appendChild(label);
    }
    var axisLabel = svgEl("text", { x: 8, y: marginTop, class: "axis-label" });
    axisLabel.textContent = "output tokens";
    svg.appendChild(axisLabel);

    // x axis ticks: start / end timestamps
    [minT, maxT].forEach(function (t) {
      var x = xOf(t);
      var label = svgEl("text", { x: x, y: height - marginBottom + 16, "text-anchor": t === minT ? "start" : "end" });
      var d = new Date(t);
      label.textContent = isNaN(d.getTime()) ? "" : d.toISOString().slice(0, 10);
      svg.appendChild(label);
    });
    var xAxisLabel = svgEl("text", { x: width - marginRight, y: height - 4, "text-anchor": "end", class: "axis-label" });
    xAxisLabel.textContent = "time";
    svg.appendChild(xAxisLabel);

    var baseline = svgEl("line", {
      x1: marginLeft, x2: width - marginRight, y1: marginTop + plotH, y2: marginTop + plotH,
      stroke: "var(--baseline)", "stroke-width": 1
    });
    svg.appendChild(baseline);

    types.forEach(function (type) {
      var series = pts.filter(function (p) { return p.type === type; }).sort(function (a, b) { return a.t - b.t; });
      var color = colorOf[type];
      if (series.length > 1) {
        var d = series.map(function (p, i) {
          return (i === 0 ? "M" : "L") + xOf(p.t).toFixed(1) + "," + yOf(p.y).toFixed(1);
        }).join(" ");
        var path = svgEl("path", { d: d, fill: "none", stroke: color, "stroke-width": 2 });
        svg.appendChild(path);
      }
      series.forEach(function (p) {
        var c = svgEl("circle", { cx: xOf(p.t), cy: yOf(p.y), r: 4, fill: color });
        var ctitle = svgEl("title", {});
        var d2 = new Date(p.t);
        ctitle.textContent = type + " @ " + (isNaN(d2.getTime()) ? p.t : d2.toISOString()) + ": " + p.y.toLocaleString() + " output tokens";
        c.appendChild(ctitle);
        svg.appendChild(c);
      });
    });

    host.appendChild(svg);

    var legend = document.createElement("div");
    legend.className = "legend";
    types.forEach(function (t) {
      var item = document.createElement("span");
      item.className = "legend-item";
      item.innerHTML = '<span class="swatch" style="background:' + colorOf[t] + '"></span>' + esc(t);
      legend.appendChild(item);
    });
    host.appendChild(legend);
  }

  function fmtModels(row) {
    var spawn = row.spawn_model || "?";
    var models = Array.isArray(row.models) ? row.models.join(",") : "?";
    return spawn + "→" + models;
  }

  function labelButtons(row) {
    if (row.agent_type !== "tierwork:bug-validator") return "";
    var current = row.label
      ? '<span class="label-tag ' + esc(row.label) + '">' + esc(row.label) + (row.note ? ": " + esc(row.note) : "") + '</span>'
      : "";
    var sid = esc(row.session_id);
    var aid = esc(row.agent_id);
    return (
      '<div class="label-controls" data-session="' + sid + '" data-agent="' + aid + '">' +
      '<button type="button" class="label-btn" data-label="true_positive">TP</button>' +
      '<button type="button" class="label-btn" data-label="false_positive">FP</button>' +
      '<button type="button" class="label-btn" data-label="unclear">?</button>' +
      '<input type="text" class="note-input" placeholder="note">' +
      current +
      "</div>"
    );
  }

  function renderTable(rows) {
    var wrap = document.getElementById("table-wrap");
    if (!rows.length) {
      wrap.innerHTML = '<div class="empty">No data yet. Run a tierwork sub-agent, or check --log points at the right file.</div>';
      return;
    }
    var sorted = rows.slice().sort(function (a, b) {
      var ta = a.ts ? Date.parse(a.ts) : 0;
      var tb = b.ts ? Date.parse(b.ts) : 0;
      return tb - ta;
    });

    var cols = ["ts", "agent_type", "models", "msgs", "tool_calls", "output_tokens", "verdict", "confidence", "needs_primary_review", "proceed", "description", "cwd", "label"];
    var head = cols.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("");

    var body = sorted.map(function (r) {
      return (
        "<tr>" +
        "<td>" + esc(r.ts) + "</td>" +
        "<td>" + esc(r.agent_type) + "</td>" +
        "<td>" + esc(fmtModels(r)) + "</td>" +
        "<td>" + esc(r.msgs) + "</td>" +
        "<td>" + esc(r.tool_calls) + "</td>" +
        "<td>" + esc(num(r.output_tokens).toLocaleString()) + "</td>" +
        "<td>" + esc(r.verdict) + "</td>" +
        "<td>" + esc(r.confidence) + "</td>" +
        "<td>" + esc(r.needs_primary_review) + "</td>" +
        "<td>" + esc(r.proceed) + "</td>" +
        '<td class="desc">' + esc(r.description) + "</td>" +
        "<td>" + esc(basename(r.cwd)) + "</td>" +
        "<td>" + labelButtons(r) + "</td>" +
        "</tr>"
      );
    }).join("");

    wrap.innerHTML = "<table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>";

    wrap.querySelectorAll(".label-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var controls = btn.closest(".label-controls");
        var sessionId = controls.getAttribute("data-session");
        var agentId = controls.getAttribute("data-agent");
        var label = btn.getAttribute("data-label");
        var noteInput = controls.querySelector(".note-input");
        var note = noteInput ? noteInput.value : "";
        setStatus("Saving label…");
        fetch("/api/label", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, agent_id: agentId, label: label, note: note })
        })
          .then(function (resp) {
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            return resp.json();
          })
          .then(function () {
            setStatus("Label saved.");
            return loadAndRender();
          })
          .catch(function (err) {
            setStatus("Label save failed: " + err.message);
          });
      });
    });
  }

  function setStatus(msg) {
    document.getElementById("status").textContent = msg || "";
  }

  function renderAll() {
    var stats = computeStats(state.rows);
    renderTiles(stats);
    renderBarChart(state.rows);
    renderLineChart(state.rows);
    renderTable(state.rows);
  }

  function loadAndRender() {
    setStatus("Loading…");
    return fetch("/api/rows")
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        return resp.json();
      })
      .then(function (rows) {
        state.rows = Array.isArray(rows) ? rows : [];
        renderAll();
        setStatus(state.rows.length ? "" : "No data yet.");
      })
      .catch(function (err) {
        setStatus("Failed to load /api/rows: " + err.message);
        state.rows = [];
        renderAll();
      });
  }

  document.getElementById("reload-btn").addEventListener("click", loadAndRender);
  loadAndRender();
})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", default=default_log_path(), help="path to reviews.jsonl")
    ap.add_argument("--labels", default="~/.tierwork/labels.jsonl", help="path to labels.jsonl")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    log_path = Path(os.path.expanduser(args.log))
    labels_path = Path(os.path.expanduser(args.labels))

    handler = make_handler(log_path, labels_path)
    server = HTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving at http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
