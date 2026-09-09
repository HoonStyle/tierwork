from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest

from bench import aggregate, budget, record_run


def record(pair, condition, *, status="completed", cost=1.0, recall=1.0, precision=1.0, semantic=True):
    return {
        "experiment_id": "exp", "run_id": f"{pair}-{condition}",
        "pair_id": pair, "fixture": "small", "condition": condition,
        "main_model": "opus", "policy_revision": "abc", "status": status,
        "maximum_total_cost_usd": 10.0,
        "metrics": {"cost_usd": cost, "duration_ms": cost * 1000, "num_turns": 2},
        "score": {
            "location_recall": recall,
            "semantic_recall": recall if semantic else None,
            "semantic_precision": precision if semantic else None,
            "semantic_review_complete": semantic,
        },
    }


class AggregateTest(unittest.TestCase):
    def test_failed_and_unpaired_runs_are_not_hidden(self):
        rows = [
            record("p1", "disabled"), record("p1", "enabled", status="failed"),
            record("p2", "disabled"),
        ]

        result = aggregate.aggregate(rows, {})["cohorts"][0]

        self.assertEqual(result["complete_pairs"], 0)
        self.assertEqual({item["status"] for item in result["incomplete_runs"]}, {"failed", "unpaired"})
        self.assertEqual(result["conclusion"], "inconclusive")

    def test_unregistered_thresholds_or_semantic_review_keep_inconclusive(self):
        rows = [record("p1", "disabled"), record("p1", "enabled", cost=0.7, semantic=False)]
        thresholds = {
            "minimum_pairs": 1,
            "recall_noninferiority_margin": 0.0,
            "precision_noninferiority_margin": 0.0,
            "minimum_cost_improvement_fraction": 0.2,
            "maximum_total_cost_usd": 10.0,
        }

        missing = aggregate.aggregate(rows, {})["cohorts"][0]
        unreviewed = aggregate.aggregate(rows, thresholds)["cohorts"][0]

        self.assertIn("not preregistered", missing["reasons"][0])
        self.assertIn("semantic review", unreviewed["reasons"][0])

    def test_claim_requires_quality_and_cost_thresholds_together(self):
        rows = [
            record("p1", "disabled", cost=1.0, recall=1.0),
            record("p1", "enabled", cost=0.7, recall=1.0),
            record("p2", "disabled", cost=2.0, recall=1.0),
            record("p2", "enabled", cost=1.4, recall=0.95, precision=0.9),
        ]
        thresholds = {
            "minimum_pairs": 2,
            "recall_noninferiority_margin": 0.05,
            "precision_noninferiority_margin": 0.1,
            "minimum_cost_improvement_fraction": 0.25,
            "maximum_total_cost_usd": 10.0,
        }

        result = aggregate.aggregate(rows, thresholds)["cohorts"][0]

        self.assertEqual(result["conclusion"], "supported")
        self.assertEqual(result["complete_pairs"], 2)
        self.assertAlmostEqual(result["paired_cost_improvement_fraction"]["mean"], 0.3)
        self.assertAlmostEqual(result["paired_semantic_recall_delta"]["mean"], -0.025)
        self.assertAlmostEqual(result["paired_semantic_precision_delta"]["mean"], -0.05)

    def test_run_metadata_preserves_raw_hash_metrics_and_failure_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw.json"
            score = root / "score.json"
            raw.write_text(json.dumps({
                "session_id": "session", "total_cost_usd": 1.25,
                "duration_ms": 500, "num_turns": 3,
                "usage": {"gpt": {"output_tokens": 10}},
            }), encoding="utf-8")
            score.write_text(json.dumps({"location_recall": 1.0}), encoding="utf-8")
            args = Namespace(
                raw=str(raw), score=str(score), output=str(root / "meta.json"),
                experiment="exp", condition="enabled", repeat=1, fixture="small",
                model="opus", policy_revision="abc", started_at="start", ended_at="end",
                run_exit=0, score_exit=0, cost_cap=10.0,
            )

            completed = record_run.build_metadata(args)
            args.run_exit = 7
            failed = record_run.build_metadata(args)
            args.run_exit = 130
            interrupted = record_run.build_metadata(args)

            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["pair_id"], "exp-small-r1")
            self.assertEqual(completed["metrics"]["cost_usd"], 1.25)
            self.assertEqual(completed["maximum_total_cost_usd"], 10.0)
            self.assertEqual(len(completed["raw_result_sha256"]), 64)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(interrupted["status"], "interrupted")

    def test_budget_totals_metadata_and_stops_on_unknown_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.meta.json").write_text(json.dumps({
                "metrics": {"cost_usd": 1.25},
            }), encoding="utf-8")
            total, missing = budget.measured_cost(root)
            self.assertEqual(total, 1.25)
            self.assertEqual(missing, [])

            (root / "b.meta.json").write_text(json.dumps({
                "metrics": {"cost_usd": None},
            }), encoding="utf-8")
            total, missing = budget.measured_cost(root)
            self.assertEqual(total, 1.25)
            self.assertEqual(missing, ["b.meta.json"])


if __name__ == "__main__":
    unittest.main()
