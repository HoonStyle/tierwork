import csv
import io
import json
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


if __name__ == "__main__":
    unittest.main()
