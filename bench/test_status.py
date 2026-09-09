import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import status


class StatusTest(unittest.TestCase):
    @staticmethod
    def diagnostics():
        return {"files": 1, "missingFiles": 0, "unreadableFiles": 0, "malformedLines": 0, "nonObjectLines": 0}

    def test_newer_running_wins_older_done_and_tied_done_wins(self):
        rows = [
            {"ts": "2026-09-09T00:00:00Z", "session_id": "s", "agent_id": "a", "status": "done"},
            {"ts": "2026-09-09T00:01:00Z", "session_id": "s", "agent_id": "a", "status": "running"},
            {"ts": "2026-09-09T00:02:00Z", "session_id": "s", "agent_id": "b", "status": "running"},
            {"ts": "2026-09-09T00:02:00Z", "session_id": "s", "agent_id": "b", "status": "done"},
        ]
        latest, skipped = status.latest_recorded(rows)
        by_agent = {row["agent_id"]: row for row in latest}
        self.assertEqual(by_agent["a"]["status"], "running")
        self.assertEqual(by_agent["b"]["status"], "done")
        self.assertEqual(skipped, {"invalidIdentity": 0, "invalidTimestamp": 0})

    def test_legacy_unknown_filters_and_recency_boundary(self):
        rows = [
            {"ts": "2026-09-09T00:00:00", "session_id": "s", "agent_id": "legacy", "runtime": "claude"},
            {"ts": "2026-09-09T00:04:00Z", "session_id": "s", "agent_id": "future", "status": "paused"},
            {"ts": "2026-09-09T00:04:30Z", "session_id": "other", "agent_id": "x", "status": "running"},
        ]
        payload = status.build_status(
            rows,
            {"files": 1, "missingFiles": 0, "unreadableFiles": 0, "malformedLines": 0, "nonObjectLines": 0},
            session="s", recent_seconds=300, now_value=datetime(2026, 9, 9, 0, 5, tzinfo=timezone.utc),
        )
        self.assertEqual([row["agentId"] for row in payload["recentlyCompleted"]], ["legacy"])
        self.assertEqual([row["agentId"] for row in payload["unknownStatus"]], ["future"])
        self.assertEqual(payload["inFlight"], [])

    def test_reader_reports_malformed_nonobject_missing_unreadable_and_invalid_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / "good.jsonl"
            good.write_text(
                json.dumps({"ts": "bad", "session_id": "s", "agent_id": "a", "status": "running"}) + "\n" +
                json.dumps({"ts": "2026-09-09T00:00:00Z", "session_id": None, "agent_id": "b"}) + "\n" +
                "{broken\n[]\n",
                encoding="utf-8",
            )
            unreadable = root / "unreadable.jsonl"
            unreadable.write_bytes(b"\xff\xfe")
            missing = root / "missing.jsonl"
            rows, diagnostics = status.read_rows([str(good), str(unreadable), str(missing)])
            latest, skipped = status.latest_recorded(rows)
            self.assertEqual(latest, [])
            self.assertEqual(diagnostics["malformedLines"], 1)
            self.assertEqual(diagnostics["nonObjectLines"], 1)
            self.assertEqual(diagnostics["unreadableFiles"], 1)
            self.assertEqual(diagnostics["missingFiles"], 1)
            self.assertEqual(skipped, {"invalidIdentity": 1, "invalidTimestamp": 1})

    def test_agent_filter_applies_after_deduplication(self):
        rows = [
            {"ts": "2026-09-09T00:00:00Z", "session_id": "s1", "agent_id": "a", "status": "done"},
            {"ts": "2026-09-09T00:01:00Z", "session_id": "s1", "agent_id": "a", "status": "running"},
            {"ts": "2026-09-09T00:01:00Z", "session_id": "s1", "agent_id": "b", "status": "running"},
        ]
        diagnostics = {"files": 1, "missingFiles": 0, "unreadableFiles": 0, "malformedLines": 0, "nonObjectLines": 0}
        payload = status.build_status(rows, diagnostics, agent="a", now_value=datetime(2026, 9, 9, 0, 2, tzinfo=timezone.utc))
        self.assertEqual([row["agentId"] for row in payload["inFlight"]], ["a"])

    def test_timestamp_offsets_naive_values_and_remaining_ties(self):
        rows = [
            {"ts": "2026-09-09T09:00:00+09:00", "session_id": "s", "agent_id": "offset", "status": "done"},
            {"ts": "2026-09-09T00:01:00Z", "session_id": "s", "agent_id": "offset", "status": "running"},
            {"ts": "2026-09-09T00:02:00", "session_id": "s", "agent_id": "tie", "status": "paused", "value": 1},
            {"ts": "2026-09-09T00:02:00Z", "session_id": "s", "agent_id": "tie", "status": "future", "value": 2},
        ]

        latest, skipped = status.latest_recorded(rows)
        by_agent = {row["agent_id"]: row for row in latest}

        self.assertEqual(by_agent["offset"]["status"], "running")
        self.assertEqual(by_agent["tie"]["value"], 2)
        self.assertEqual(skipped, {"invalidIdentity": 0, "invalidTimestamp": 0})

    def test_session_filter_applies_after_cross_session_deduplication(self):
        rows = [
            {"ts": "2026-09-09T00:00:00Z", "session_id": "s1", "agent_id": "a", "status": "done"},
            {"ts": "2026-09-09T00:01:00Z", "session_id": "s2", "agent_id": "a", "status": "running"},
        ]

        payload = status.build_status(
            rows, self.diagnostics(), session="s1",
            now_value=datetime(2026, 9, 9, 0, 2, tzinfo=timezone.utc),
        )

        self.assertEqual([row["sessionId"] for row in payload["recentlyCompleted"]], ["s1"])
        self.assertEqual(payload["inFlight"], [])

    def test_recent_boundary_future_timestamp_and_empty_input(self):
        rows = [
            {"ts": "2026-09-09T00:00:00Z", "session_id": "s", "agent_id": "boundary", "status": "done"},
            {"ts": "2026-09-09T00:05:01Z", "session_id": "s", "agent_id": "future", "status": "done"},
            {"ts": "2026-09-09T00:06:00Z", "session_id": "s", "agent_id": "future-running", "status": "running"},
        ]
        now = datetime(2026, 9, 9, 0, 5, tzinfo=timezone.utc)

        payload = status.build_status(rows, self.diagnostics(), recent_seconds=300, now_value=now)
        empty = status.build_status([], self.diagnostics(), now_value=now)

        self.assertEqual([row["agentId"] for row in payload["recentlyCompleted"]], ["boundary"])
        self.assertEqual(payload["diagnostics"]["futureTimestamps"], 2)
        self.assertEqual(payload["inFlight"], [])
        self.assertEqual(empty["inFlight"], [])
        self.assertEqual(empty["recentlyCompleted"], [])
        self.assertEqual(empty["unknownStatus"], [])

    def test_directory_reader_is_deterministic_and_tags_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "b.jsonl").write_text(json.dumps({
                "ts": "2026-09-09T00:01:00Z", "session_id": "s", "agent_id": "b", "status": "running",
            }) + "\n", encoding="utf-8")
            (root / "a.jsonl").write_text(json.dumps({
                "ts": "2026-09-09T00:00:00Z", "session_id": "s", "agent_id": "a", "status": "done",
            }) + "\n", encoding="utf-8")

            rows, diagnostics = status.read_rows([str(root)])

            self.assertEqual([(row["agent_id"], row["source"]) for row in rows], [("a", "a.jsonl"), ("b", "b.jsonl")])
            self.assertEqual(diagnostics["files"], 2)

    def test_cli_json_schema_and_text_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "events.jsonl"
            log.write_text(json.dumps({
                "ts": "2026-09-09T00:00:00Z", "session_id": "s", "agent_id": "a", "status": "running",
            }) + "\n", encoding="utf-8")
            script = str(Path(__file__).with_name("status.py"))

            json_run = subprocess.run(
                [sys.executable, script, "--log", str(log), "--json"],
                check=True, capture_output=True, text=True,
            )
            text_run = subprocess.run(
                [sys.executable, script, "--log", str(log)],
                check=True, capture_output=True, text=True,
            )
            payload = json.loads(json_run.stdout)

            self.assertEqual(set(payload), {
                "authority", "limitations", "filters", "inFlight",
                "recentlyCompleted", "unknownStatus", "diagnostics",
            })
            self.assertIn("recorded_hook_status_only", payload["authority"])
            self.assertIn("not process liveness", text_run.stdout.lower())
            self.assertIn("not proof the result was collected", text_run.stdout.lower())


if __name__ == "__main__":
    unittest.main()
