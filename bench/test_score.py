import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bench import score


class ScoreContractTest(unittest.TestCase):
    KEY = """# defects
bug-a|src/a.py:10
bug-b|src/b.py:20-22
bug-c|src/c.py:30
"""

    def test_exact_range_outside_and_missed(self):
        report = score.score_text(
            "A src/a.py:10, B src/b.py:19-21, extra src/b.py:99", self.KEY
        )
        statuses = {item["id"]: item["classification"] for item in report["answer_entries"]}
        self.assertEqual(statuses, {"bug-a": "exact", "bug-b": "range", "bug-c": "missed"})
        self.assertEqual(report["counts"]["outside_references"], 1)
        self.assertAlmostEqual(report["location_recall"], 2 / 3)
        self.assertAlmostEqual(report["location_precision_candidate"], 2 / 3)
        self.assertTrue(report["semantic_review_required"])

    def test_duplicate_and_ambiguous_are_not_auto_confirmed(self):
        duplicate = score.score_text("src/a.py:10 src/a.py:10", self.KEY)
        self.assertEqual(duplicate["answer_entries"][0]["classification"], "duplicate")
        self.assertTrue(duplicate["answer_entries"][0]["location_candidate"])
        self.assertTrue(duplicate["answer_entries"][0]["semantic_review_required"])

        overlapping = """bug-a|src/a.py:10
bug-also|src/a.py:10-12
"""
        ambiguous = score.score_text("src/a.py:10", overlapping)
        self.assertEqual([item["classification"] for item in ambiguous["answer_entries"]], ["ambiguous", "ambiguous"])
        self.assertEqual(ambiguous["references"][0]["classification"], "ambiguous")

    def test_answer_key_ranges_and_duplicate_ids_are_validated(self):
        self.assertEqual(score.parse_answer_key("x|a.py:4-6")[0]["end"], 6)
        with self.assertRaises(ValueError):
            score.parse_answer_key("x|a.py:6-4")
        with self.assertRaises(ValueError):
            score.parse_answer_key("x|a.py:4\nx|b.py:8")

    def test_same_line_false_claim_remains_a_semantic_review_candidate(self):
        report = score.score_text("A false explanation cites src/a.py:10", self.KEY)

        self.assertEqual(report["answer_entries"][0]["classification"], "exact")
        self.assertEqual(report["authority"], "location_candidates_only")
        self.assertFalse(report["semantic_review_complete"])

        reviewed = score.apply_judgments(report, {
            "reviewer": "independent-reviewer", "independent": True,
            "references": [{"index": 0, "verdict": "false_positive"}],
        })
        self.assertTrue(reviewed["semantic_review_complete"])
        self.assertEqual(reviewed["semantic_recall"], 0.0)
        self.assertEqual(reviewed["semantic_precision"], 0.0)

    def test_true_positive_judgment_must_name_a_location_candidate(self):
        report = score.score_text("src/a.py:99", self.KEY)
        with self.assertRaises(ValueError):
            score.apply_judgments(report, {
                "reviewer": "r", "independent": True,
                "references": [{"index": 0, "verdict": "true_positive", "answer_id": "bug-a"}],
            })

    def test_json_cli_output_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = root / "result.json"
            key = root / "ANSWER.md"
            result.write_text(json.dumps({"result": "src/a.py:10 src/a.py:10"}), encoding="utf-8")
            key.write_text("bug-a|src/a.py:10\n", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("score.py")), str(result), str(key), "--json"],
                check=True, capture_output=True, text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["counts"]["duplicate"], 1)
            self.assertTrue(payload["semantic_review_required"])


if __name__ == "__main__":
    unittest.main()
