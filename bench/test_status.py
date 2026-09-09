import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import status


class StatusTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
