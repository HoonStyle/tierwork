import importlib.util
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HOOK_PATH = Path(__file__).parents[1] / "hooks" / "log-subagent.py"
SPEC = importlib.util.spec_from_file_location("tierwork_log_subagent", HOOK_PATH)
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


def assistant_record(text, *, model="claude-opus", input_tokens=1, output_tokens=2):
    return {
        "type": "assistant",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 4,
            },
            "content": [
                {"type": "tool_use", "name": "check"},
                {"type": "text", "text": text},
            ],
        },
    }


class HookParserTest(unittest.TestCase):
    def test_claude_stats_and_fields_are_tolerant_and_deterministic(self):
        records = [
            assistant_record("first", model="m1"),
            "not-an-object",
            assistant_record(
                "VERDICT: confirmed. confidence: 87; check_status: passed, "
                "needs_primary_review: no: proceed: yes",
                model="m2", input_tokens=5, output_tokens=6,
            ),
        ]

        stats = hook.compute_stats(records)

        self.assertEqual(stats["models"], ["m1", "m2"])
        self.assertEqual(stats["msgs"], 2)
        self.assertEqual(stats["tool_calls"], 2)
        self.assertEqual(stats["input_tokens"], 6)
        self.assertEqual(stats["output_tokens"], 8)
        self.assertEqual(stats["cache_read"], 6)
        self.assertEqual(stats["cache_create"], 8)
        self.assertEqual(hook.parse_field(stats["last_text"], "verdict"), "confirmed")
        self.assertEqual(hook.parse_field(stats["last_text"], "check_status"), "passed")
        self.assertEqual(hook.parse_field("nothing here", "verdict"), "")

    def test_codex_stats_use_last_cumulative_usage_and_task_complete_text(self):
        records = [
            {"type": "turn_context", "payload": {"model": "gpt-a"}},
            {"type": "response_item", "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "draft"}],
            }},
            {"type": "response_item", "payload": {"type": "custom_tool_call"}},
            {"type": "token_usage_record", "payload": {"thread_token_usage": {
                "input_tokens": 10, "output_tokens": 2,
            }}},
            {"type": "token_usage_record", "payload": {"thread_token_usage": {
                "input_tokens": 20, "output_tokens": 4,
                "cached_input_tokens": 7, "cache_write_input_tokens": 3,
            }}},
            {"type": "event_msg", "payload": {
                "type": "task_complete", "last_assistant_message": "final",
            }},
        ]

        stats = hook.compute_codex_stats(records)

        self.assertEqual(stats, {
            "models": ["gpt-a"], "msgs": 1, "input_tokens": 20,
            "output_tokens": 4, "cache_read": 7, "cache_create": 3,
            "tool_calls": 1, "last_text": "final",
        })
        self.assertTrue(hook.is_codex_input({"model": "gpt-a"}))
        self.assertTrue(hook.is_codex_input({"agent_transcript_path": "x"}))
        self.assertFalse(hook.is_codex_input({"transcript_path": "x"}))

    def test_rollout_fallback_verifies_session_meta_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            sessions = home / ".codex" / "sessions"
            sessions.mkdir(parents=True)
            wrong = sessions / "rollout-target-newer.jsonl"
            correct = sessions / "rollout-unrelated-name.jsonl"
            wrong.write_text(json.dumps({
                "type": "session_meta", "payload": {"id": "someone-else"},
            }) + "\n", encoding="utf-8")
            correct.write_text(json.dumps({
                "type": "session_meta", "payload": {"id": "target"},
            }) + "\n", encoding="utf-8")
            os.utime(wrong, (2_000_000_000, 2_000_000_000))
            os.utime(correct, (1_900_000_000, 1_900_000_000))

            with mock.patch.object(hook.os.path, "expanduser", return_value=str(home)):
                found = hook.find_rollout_by_thread_id("target")

            self.assertEqual(Path(found), correct)


class HookProcessTest(unittest.TestCase):
    def run_hook(self, payload, log, *, raw=None):
        env = os.environ.copy()
        env["TIERWORK_LOG"] = str(log)
        return subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=raw if raw is not None else json.dumps(payload),
            capture_output=True, text=True, env=env, check=False,
        )

    @staticmethod
    def read_log(log):
        if not log.exists():
            return []
        text = log.read_text(encoding="utf-8")
        records = []
        for line in text.splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AssertionError(f"invalid JSONL record {line!r}; file={text!r}") from exc
        return records

    def test_claude_stop_prefers_derived_agent_transcript(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "reviews.jsonl"
            main = root / "main.jsonl"
            main.write_text(json.dumps(assistant_record("verdict: refuted")) + "\n", encoding="utf-8")
            subagents = root / "s" / "subagents"
            subagents.mkdir(parents=True)
            agent = subagents / "agent-a.jsonl"
            agent.write_text(json.dumps(assistant_record(
                "verdict: confirmed confidence: 91 check_status: passed "
                "needs_primary_review: no proceed: yes",
            )) + "\n", encoding="utf-8")
            agent.with_suffix(".meta.json").write_text(json.dumps({
                "model": "claude-opus", "description": "derived",
            }), encoding="utf-8")

            result = self.run_hook({
                "hook_event_name": "SubagentStop", "session_id": "s",
                "agent_id": "a", "agent_type": "tierwork:bug-validator",
                "transcript_path": str(main), "cwd": str(root),
            }, log)
            record = self.read_log(log)[0]

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(record["verdict"], "confirmed")
            self.assertEqual(record["check_status"], "passed")
            self.assertEqual(record["description"], "derived")

    def test_unmarked_main_transcript_is_not_misattributed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "reviews.jsonl"
            main = root / "main.jsonl"
            main.write_text(json.dumps(assistant_record("verdict: confirmed")) + "\n", encoding="utf-8")

            self.run_hook({
                "hook_event_name": "SubagentStop", "session_id": "s",
                "agent_id": "missing", "agent_type": "tierwork:bug-validator",
                "transcript_path": str(main),
            }, log)
            record = self.read_log(log)[0]

            self.assertEqual(record["models"], [])
            self.assertEqual(record["msgs"], 0)
            self.assertIsNone(record["verdict"])

    def test_codex_stop_and_missing_or_malformed_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "reviews.jsonl"
            rollout = root / "rollout.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "a", "source": {
                    "subagent": {"thread_spawn": {"agent_role": "tierwork:bug-validator"}},
                }}},
                {"type": "turn_context", "payload": {"model": "gpt-6"}},
                {"type": "token_usage_record", "payload": {"thread_token_usage": {
                    "input_tokens": 12, "output_tokens": 5,
                }}},
            ]
            rollout.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")

            result = self.run_hook({
                "hook_event_name": "SubagentStop", "session_id": "s",
                "agent_id": "a", "agent_type": "default", "model": "gpt-6",
                "agent_transcript_path": str(rollout),
                "last_assistant_message": "verdict: confirmed check_status: passed",
            }, log)
            for raw in ("", "{broken", "[]"):
                malformed = self.run_hook({}, log, raw=raw)
                self.assertEqual(malformed.returncode, 0)
                self.assertEqual(malformed.stdout, "")
            record = self.read_log(log)[0]

            self.assertEqual(result.returncode, 0)
            self.assertEqual(record["runtime"], "codex")
            self.assertEqual(record["agent_type"], "tierwork:bug-validator")
            self.assertEqual(record["output_tokens"], 5)
            self.assertEqual(record["check_status"], "passed")

    def test_concurrent_start_appends_remain_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "reviews.jsonl"
            env = os.environ.copy()
            env["TIERWORK_LOG"] = str(log)
            payloads = [json.dumps({
                    "hook_event_name": "SubagentStart", "session_id": "s",
                    "agent_id": str(index), "agent_type": "tierwork:bug-hunter",
                }) for index in range(12)]

            def invoke(payload):
                return subprocess.run(
                    [sys.executable, str(HOOK_PATH)], input=payload,
                    capture_output=True, text=True, env=env, check=False,
                )

            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(invoke, payloads))
            self.assertTrue(all(result.returncode == 0 for result in results))
            records = self.read_log(log)

            self.assertEqual(len(records), 12)
            self.assertEqual({row["agent_id"] for row in records}, {str(i) for i in range(12)})

    def test_minimal_shell_fallback_records_lifecycle_only(self):
        if os.name == "nt":
            self.skipTest("minimal fallback fixture requires a native POSIX bash environment")
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "reviews.jsonl"
            env = os.environ.copy()
            env["TIERWORK_LOG"] = log.as_posix()
            env["TIERWORK_TEST_FALLBACK"] = "minimal"
            payload = json.dumps({
                "hook_event_name": "SubagentStop", "session_id": "s",
                "agent_id": "a", "agent_type": "tierwork:bug-validator",
            })

            result = subprocess.run(
                [bash, "-lc", HOOK_PATH.with_suffix(".sh").as_posix()], input=payload,
                capture_output=True, text=True, env=env, check=False,
            )
            record = self.read_log(log)[0]

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(record["status"], "done")
            self.assertEqual(record["missing_tool"], "python3+jq")
            self.assertNotIn("verdict", record)
            self.assertNotIn("check_status", record)


if __name__ == "__main__":
    unittest.main()
