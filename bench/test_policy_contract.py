from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class PolicyContractTest(unittest.TestCase):
    def test_task_boundaries_cover_document_workflow_regressions(self):
        # Static prompt guards, not evidence of live model compliance.
        scenarios = {
            "document_contract": ["## Task-contract boundary", "mandatory stages"],
            "pointer_access": ["when the task permits", "required content"],
            "arbitrary_read_limit": ["Never invent read-count"],
            "interrupted_assignment": ["Do not silently change scope or restart", "affected remainder"],
            "changed_artifact": ["matching artifact version, scope, and assumptions", "Recheck affected claims"],
            "reuse_reporting": ["reused versus newly performed", "executor, input version"],
            "unavailable_evidence": ["Missing evidence means unknown, not false or absent"],
            "self_review": ["self-review, not independent validation"],
            "unsupported_savings": ["counterfactual savings without a comparable measurement"],
        }
        for path in ("hooks/policy.md", "skills/subagent-delegation/SKILL.md"):
            text = " ".join(read(path).split())
            for scenario, phrases in scenarios.items():
                with self.subTest(path=path, scenario=scenario):
                    for phrase in phrases:
                        self.assertIn(phrase, text)

    def test_optional_optimizations_do_not_replace_artifacts_or_stages(self):
        skill = read("skills/subagent-delegation/SKILL.md")
        self.assertIn("For optional work only", skill)
        self.assertIn("Preserve the task's required output format and artifact writer", skill)
        self.assertIn("For code-review findings", skill)
        self.assertNotIn("agents never write them", skill)
        self.assertIn("## Prompt changelog", read("README.md"))

    def test_validator_outputs_match_across_harnesses(self):
        claude = read("agents/bug-validator.md")
        codex = read("codex/agents/bug-validator.toml")
        required = [
            "check_status: passed|failed|unavailable",
            "`passed` means an applicable check completed",
            "`failed` means an applicable check completed and contradicts the finding",
            "`unavailable` means no applicable check exists or the check was",
            "check_status` is not `passed",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, claude)
                self.assertIn(phrase.replace("`", "") if phrase.startswith("check_status`") else phrase, codex)

    def test_fast_path_requires_confirmed_passed_and_threshold(self):
        policy = read("hooks/policy.md")
        skill = read("skills/subagent-delegation/SKILL.md")
        for text in (policy, skill):
            self.assertIn("`verdict: confirmed`", text)
            self.assertIn("`check_status: passed`", text)
            self.assertIn("confidence >= 70", text)
            self.assertIn("failed check refutes the finding", text)
        self.assertNotIn(
            "confirmed with confidence >= 70; report them",
            policy,
        )

    def test_unavailable_or_missing_status_requires_review(self):
        validator = read("agents/bug-validator.md")
        policy = read("hooks/policy.md")
        self.assertIn("check_status` is not `passed`", validator)
        self.assertIn("missing/unknown", policy)
        self.assertIn("`check_status: unavailable`", policy)

    def test_hook_loggers_preserve_check_status(self):
        python_hook = read("hooks/log-subagent.py")
        shell_hook = read("hooks/log-subagent.sh")
        self.assertGreaterEqual(
            python_hook.count('parse_field(last_text, "check_status")'), 2
        )
        self.assertGreaterEqual(
            python_hook.count('"check_status": check_status or None'), 2
        )
        self.assertIn("--arg check_status", shell_hook)
        self.assertIn("check_status: (if $check_status", shell_hook)
        self.assertIn("no-Python/no-jq minimal", read("README.md"))

    def test_benchmark_fixture_is_documented_as_historical(self):
        fixture = read("bench/fixtures/small/base/agents/bug-validator.md")
        changelog = read("README.md")
        self.assertNotIn("check_status:", fixture)
        self.assertIn("intentional historical policy snapshot", changelog)


if __name__ == "__main__":
    unittest.main()
