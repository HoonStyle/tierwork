import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import dashboard
from recorded_state import latest_recorded, recorded_status


class RecordedStateMergeTest(unittest.TestCase):
    def test_latest_timestamp_wins_and_same_time_done_wins(self):
        rows = [
            {"ts": "2026-09-09T00:00:00Z", "session_id": "s", "agent_id": "new-run", "status": "done"},
            {"ts": "2026-09-09T00:01:00Z", "session_id": "s", "agent_id": "new-run", "status": "running"},
            {"ts": "2026-09-09T00:00:00Z", "session_id": "s", "agent_id": "new-done", "status": "running"},
            {"ts": "2026-09-09T00:01:00Z", "session_id": "s", "agent_id": "new-done", "status": "done"},
            {"ts": "2026-09-09T00:02:00Z", "session_id": "s", "agent_id": "tie", "status": "running"},
            {"ts": "2026-09-09T00:02:00Z", "session_id": "s", "agent_id": "tie", "status": "done"},
        ]

        merged = dashboard.dedup_rows(rows)
        by_agent = {row["agent_id"]: row for row in merged}

        self.assertEqual(by_agent["new-run"]["status"], "running")
        self.assertEqual(by_agent["new-done"]["status"], "done")
        self.assertEqual(by_agent["tie"]["status"], "done")

    def test_sessions_are_separate_and_unknown_is_not_completion(self):
        rows = [
            {"ts": "2026-09-09T00:00:00Z", "session_id": "s1", "agent_id": "a", "status": "done"},
            {"ts": "2026-09-09T00:01:00Z", "session_id": "s2", "agent_id": "a", "status": "paused"},
        ]

        merged = dashboard.dedup_rows(rows)

        self.assertEqual(len(merged), 2)
        self.assertEqual(recorded_status(merged[1]), "unknown")

    def test_invalid_identity_and_timestamp_are_diagnostic_not_rows(self):
        rows = [
            {"ts": "2026-09-09T00:00:00Z", "session_id": "", "agent_id": "a", "status": "done"},
            {"ts": "bad", "session_id": "s", "agent_id": "b", "status": "done"},
            {"ts": "2026-09-09T00:02:00Z", "session_id": "s", "agent_id": "c", "status": "future"},
        ]

        merged, diagnostics = latest_recorded(rows)

        self.assertEqual([row["agent_id"] for row in merged], ["c"])
        self.assertEqual(recorded_status(merged[0]), "unknown")
        self.assertEqual(diagnostics, {"invalidIdentity": 1, "invalidTimestamp": 1})
        self.assertNotIn("generation", merged[0])

    def test_api_export_helpers_and_merge_cli_share_the_same_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "events.jsonl"
            labels = root / "labels.jsonl"
            output = root / "merged.jsonl"
            rows = [
                {"ts": "2026-09-09T00:00:00Z", "session_id": "s", "agent_id": "a", "status": "done"},
                {"ts": "2026-09-09T00:01:00Z", "session_id": "s", "agent_id": "a", "status": "running"},
                {"ts": "2026-09-09T00:02:00Z", "session_id": "s", "agent_id": "b", "status": "paused"},
            ]
            source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            api_rows = dashboard.merged_rows([source], labels)
            csv_rows = list(csv.DictReader(io.StringIO(dashboard.rows_to_csv(api_rows))))
            subprocess.run(
                [sys.executable, str(Path(__file__).with_name("merge.py")), str(source), "-o", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            cli_rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

            self.assertEqual([(r["agent_id"], r["status"]) for r in api_rows], [("a", "running"), ("b", "paused")])
            self.assertEqual([(r["agent_id"], r["status"]) for r in cli_rows], [("a", "running"), ("b", "paused")])
            self.assertEqual([(r["agent_id"], r["status"]) for r in csv_rows], [("a", "running"), ("b", "paused")])


class LogTailerTest(unittest.TestCase):
    def make_tailer(self, path, labels):
        broadcasts = []
        tailer = dashboard.LogTailer([path], labels)
        tailer._broadcast = lambda event, rows: broadcasts.append((event, rows))
        tailer._poll_once()  # baseline the existing file
        return tailer, broadcasts

    @staticmethod
    def append(path, data):
        with path.open("ab") as handle:
            handle.write(data)

    def test_split_writes_and_utf8_boundary_emit_once_after_newline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "events.jsonl"
            log.write_bytes(b"")
            tailer, broadcasts = self.make_tailer(log, root / "labels.jsonl")
            row = {
                "ts": "2026-09-09T00:00:00Z",
                "session_id": "s",
                "agent_id": "unicode",
                "status": "done",
                "description": "한글",
            }
            encoded = json.dumps(row, ensure_ascii=False).encode("utf-8")
            split = encoded.index("한".encode("utf-8"))

            self.append(log, encoded[:split + 1])
            tailer._poll_once()
            self.append(log, encoded[split + 1:split + 2])
            tailer._poll_once()
            self.append(log, encoded[split + 2:] + b"\n")
            tailer._poll_once()

            self.assertEqual(len(broadcasts), 1)
            self.assertEqual(broadcasts[0][0], "rows")
            self.assertEqual(broadcasts[0][1][0]["description"], "한글")

    def test_complete_rows_emit_while_next_partial_waits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "events.jsonl"
            log.write_bytes(b"")
            tailer, broadcasts = self.make_tailer(log, root / "labels.jsonl")

            def encoded(agent):
                agent = str(agent)
                return json.dumps({
                    "ts": f"2026-09-09T00:00:0{agent}Z",
                    "session_id": "s",
                    "agent_id": agent,
                    "status": "done",
                }).encode("utf-8")

            third = encoded(3)
            self.append(log, encoded(1) + b"\n" + encoded(2) + b"\n" + third[:10])
            tailer._poll_once()
            self.append(log, third[10:] + b"\n")
            tailer._poll_once()

            self.assertEqual([[row["agent_id"] for row in item[1]] for item in broadcasts], [["1", "2"], ["3"]])

    def test_crlf_blank_and_bad_complete_records_are_counted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "events.jsonl"
            log.write_bytes(b"")
            tailer, broadcasts = self.make_tailer(log, root / "labels.jsonl")
            valid = json.dumps({
                "ts": "2026-09-09T00:00:00Z",
                "session_id": "s",
                "agent_id": "valid",
                "status": "done",
            }).encode("utf-8")

            self.append(log, b"\r\n{bad}\r\n[]\r\n\xff\r\n" + valid + b"\r\n")
            tailer._poll_once()

            self.assertEqual([row["agent_id"] for row in broadcasts[0][1]], ["valid"])
            self.assertEqual(tailer.diagnostics(), {
                "malformedRecords": 1,
                "invalidUtf8Records": 1,
                "nonObjectRecords": 1,
            })

    def test_truncate_and_rotation_discard_old_fragments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "events.jsonl"
            log.write_bytes(b"")
            tailer, broadcasts = self.make_tailer(log, root / "labels.jsonl")

            self.append(log, b'{"old":"partial"')
            tailer._poll_once()
            log.write_bytes(b"")
            tailer._poll_once()
            after_truncate = json.dumps({
                "ts": "2026-09-09T00:00:00Z", "session_id": "s",
                "agent_id": "after-truncate", "status": "done",
            }).encode("utf-8") + b"\n"
            self.append(log, after_truncate)
            tailer._poll_once()

            self.append(log, b'{"another":"partial"')
            tailer._poll_once()
            replacement = root / "replacement.jsonl"
            replacement.write_bytes(json.dumps({
                "ts": "2026-09-09T00:00:01Z", "session_id": "s",
                "agent_id": "after-rotation", "status": "done",
            }).encode("utf-8") + b"\n")
            os.replace(replacement, log)
            tailer._poll_once()

            self.assertEqual([[row["agent_id"] for row in item[1]] for item in broadcasts], [
                ["after-truncate"], ["after-rotation"],
            ])


if __name__ == "__main__":
    unittest.main()
