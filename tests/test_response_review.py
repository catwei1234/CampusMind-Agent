import unittest

from app.core.enums import IntentType, RiskLevel
from app.services.response_review import ResponseReviewer
from app.services.skills import MindBridgeSkillLibrary


class ResponseReviewerTests(unittest.TestCase):
    def test_valid_high_risk_response_passes_without_model_call(self):
        skills = MindBridgeSkillLibrary.response_skills(IntentType.RISK, RiskLevel.HIGH, "high risk")
        required_terms = [term for skill in skills for term in skill.output_schema.get("requiredTerms", [])]
        output = "安全支持步骤" * 12 + " ".join(required_terms)

        review = ResponseReviewer.review(output, skills, RiskLevel.HIGH)

        self.assertTrue(review.valid)
        self.assertEqual(review.decision, "PASS")
        self.assertFalse(review.requires_escalation)

    def test_invalid_high_risk_response_is_flagged_for_escalation(self):
        skills = MindBridgeSkillLibrary.response_skills(IntentType.RISK, RiskLevel.HIGH, "high risk")

        review = ResponseReviewer.review("太短", skills, RiskLevel.HIGH)

        self.assertFalse(review.valid)
        self.assertEqual(review.decision, "FLAG")
        self.assertTrue(review.requires_escalation)
        self.assertTrue(any(code.startswith("MIN_LENGTH:") for code in review.finding_codes))
        self.assertTrue(any(code.startswith("MISSING_REQUIRED_TERM:") for code in review.finding_codes))

    def test_high_risk_response_without_help_seeking_is_flagged(self):
        skills = MindBridgeSkillLibrary.response_skills(IntentType.RISK, RiskLevel.HIGH, "high risk")

        review = ResponseReviewer.review("我理解你现在非常痛苦，我们先慢慢把感受说出来。", skills, RiskLevel.HIGH)

        self.assertFalse(review.valid)
        self.assertIn("HIGH_RISK_MISSING_HELP_SEEKING", review.finding_codes)

    def test_response_exposing_internal_risk_label_is_flagged(self):
        skills = MindBridgeSkillLibrary.response_skills(IntentType.CONSULT, RiskLevel.LOW, "压力")

        review = ResponseReviewer.review("你的风险等级是 LOW，所以不用担心。", skills, RiskLevel.LOW)

        self.assertFalse(review.valid)
        self.assertIn("EXPOSED_INTERNAL_RISK_LABEL", review.finding_codes)


if __name__ == "__main__":
    unittest.main()
