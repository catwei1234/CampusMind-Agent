import unittest

from app.core.enums import IntentType
from app.schemas.dtos import AiMessage
from app.services.safety_verifier import SafetyVerifierService, VerificationBand


class SafetyVerifierServiceTests(unittest.TestCase):
    def test_upgrades_implicit_risk_from_context(self):
        verifier = SafetyVerifierService()

        result = verifier.verify(
            "\u53ef\u80fd\u4ee5\u540e\u4e0d\u7528\u518d\u9ebb\u70e6\u5927\u5bb6\u4e86",
            "\u7528\u6237\u6700\u8fd1\u8868\u8fbe\u6491\u4e0d\u4e0b\u53bb\uff0c\u770b\u4e0d\u5230\u4ee5\u540e",
            [AiMessage(role="user", content="\u6211\u8fd9\u51e0\u5929\u4e00\u76f4\u5f88\u5d29\u6e83")],
            IntentType.CHAT,
        )

        self.assertEqual(result.verified_intent, IntentType.RISK)
        self.assertTrue(result.upgraded)
        self.assertEqual(result.decision_band, VerificationBand.UPGRADE)
        self.assertGreaterEqual(result.final_risk_score, verifier.risk_upgrade_threshold)

    def test_upgrades_chat_to_consult_from_memory(self):
        verifier = SafetyVerifierService()

        result = verifier.verify(
            "\u8fd8\u597d",
            "\u7528\u6237\u6700\u8fd1\u957f\u671f\u5931\u7720\uff0c\u611f\u89c9\u5b64\u72ec\u4e14\u538b\u529b\u5f88\u5927",
            [],
            IntentType.CHAT,
        )

        self.assertEqual(result.verified_intent, IntentType.CONSULT)
        self.assertTrue(result.upgraded)
        self.assertGreaterEqual(result.final_consult_score, verifier.consult_upgrade_threshold)

    def test_upgrades_consult_to_risk_when_strong_signal_appears(self):
        verifier = SafetyVerifierService()

        result = verifier.verify(
            "\u6211\u6491\u4e0d\u4e0b\u53bb\u4e86\uff0c\u624b\u8fb9\u6709\u5200",
            "",
            [],
            IntentType.CONSULT,
        )

        self.assertEqual(result.verified_intent, IntentType.RISK)
        self.assertTrue(result.upgraded)
        self.assertGreater(result.strong_risk_score, 0.0)

    def test_keeps_normal_task_as_chat(self):
        verifier = SafetyVerifierService()

        result = verifier.verify(
            "\u5e2e\u6211\u770b\u770b python \u62a5\u9519\u65e5\u5fd7",
            "",
            [],
            IntentType.CHAT,
        )

        self.assertEqual(result.verified_intent, IntentType.CHAT)
        self.assertFalse(result.upgraded)
        self.assertEqual(result.decision_band, VerificationBand.CLEAR)

    def test_never_downgrades_risk(self):
        verifier = SafetyVerifierService()

        result = verifier.verify("\u5e2e\u6211\u5199\u4e00\u6bb5\u4ee3\u7801", "", [], IntentType.RISK)

        self.assertEqual(result.verified_intent, IntentType.RISK)
        self.assertFalse(result.upgraded)
        self.assertEqual(result.decision_band, VerificationBand.UPGRADE)


if __name__ == "__main__":
    unittest.main()
