import copy
import json
from pathlib import Path
import unittest

from app.rubric_eval.runner import evaluate, score_judgment, validate_judgment


class RubricEvaluationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "app/rubric_eval"
        self.rubric = json.loads((root / "rubric.json").read_text(encoding="utf-8"))
        self.samples = json.loads((root / "demo.json").read_text(encoding="utf-8"))["samples"]

    def test_safety_failure_cannot_be_offset_by_other_scores(self):
        judgment = copy.deepcopy(self.samples[0]["fixture_judgment"])
        for dimension in judgment["scores"].values():
            dimension["value"] = 5
        judgment["violations"] = ["DIAGNOSIS"]
        result = score_judgment(judgment, self.rubric)
        self.assertEqual(result["weightedScore"], 100)
        self.assertFalse(result["passed"])

    def test_judge_errors_count_in_pass_rate(self):
        def judge(sample, _):
            if sample["id"] == self.samples[1]["id"]:
                raise ValueError("broken judge")
            return sample["fixture_judgment"]

        report = evaluate(self.samples, self.rubric, judge)
        self.assertEqual(report["errorCases"], 1)
        self.assertEqual(report["passRate"], 0.5)
        self.assertEqual(report["failureIds"], [self.samples[1]["id"]])

    def test_rejects_fabricated_evidence_and_out_of_range_scores(self):
        judgment = copy.deepcopy(self.samples[0]["fixture_judgment"])
        judgment["scores"]["safety"]["evidence"] = "not in response"
        with self.assertRaises(ValueError):
            validate_judgment(judgment, self.samples[0], self.rubric)
        judgment["scores"]["safety"].update(evidence="", value=6)
        with self.assertRaises(ValueError):
            validate_judgment(judgment, self.samples[0], self.rubric)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            evaluate([self.samples[0], self.samples[0]], self.rubric, lambda s, _: s["fixture_judgment"])

    def test_dimensions_and_violation_codes_checked(self):
        judgment = copy.deepcopy(self.samples[0]["fixture_judgment"])
        judgment["violations"] = ["UNKNOWN"]
        with self.assertRaises(ValueError):
            validate_judgment(judgment, self.samples[0], self.rubric)


if __name__ == "__main__":
    unittest.main()
