from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.enums import IntentType
from app.schemas.dtos import AiMessage
from app.services.knowledge import keyword_score, token_cosine


RISK_PROTOTYPES = [
    "\u6211\u4e0d\u60f3\u6d3b\u4e86",
    "\u6211\u60f3\u4f24\u5bb3\u81ea\u5df1",
    "\u6211\u5df2\u7ecf\u8ba1\u5212\u597d\u4e86\u7ed3\u675f\u751f\u547d",
    "\u6211\u60f3\u4ece\u697c\u4e0a\u8df3\u4e0b\u53bb",
    "\u6211\u60f3\u4f24\u5bb3\u522b\u4eba",
    "\u6211\u53ef\u80fd\u4ee5\u540e\u4e0d\u7528\u518d\u9ebb\u70e6\u5927\u5bb6\u4e86",
    "\u6211\u770b\u4e0d\u5230\u4ee5\u540e",
    "\u6211\u6491\u4e0d\u4e0b\u53bb\u4e86",
    "\u6d3b\u7740\u6ca1\u6709\u610f\u4e49",
    "\u6211\u6015\u81ea\u5df1\u63a7\u5236\u4e0d\u4f4f",
]

CONSULT_PROTOTYPES = [
    "\u6211\u6700\u8fd1\u538b\u529b\u5f88\u5927",
    "\u6211\u665a\u4e0a\u7761\u4e0d\u7740",
    "\u6211\u89c9\u5f97\u5f88\u5b64\u72ec",
    "\u6211\u60c5\u7eea\u4f4e\u843d\u5f88\u4e45",
    "\u6211\u9700\u8981\u5fc3\u7406\u54a8\u8be2\u5e2e\u52a9",
    "\u6211\u6491\u4e0d\u4f4f\u4f46\u4e0d\u77e5\u9053\u600e\u4e48\u529e",
    "\u6211\u548c\u540c\u5b66\u5173\u7cfb\u5f88\u5dee\u5f88\u7126\u8651",
    "\u6211\u4e00\u76f4\u5931\u7720\u6ca1\u7cbe\u795e",
]

RISK_STRONG_TERMS = [
    "\u81ea\u6740",
    "\u81ea\u6b8b",
    "\u8f7b\u751f",
    "\u4e0d\u60f3\u6d3b",
    "\u7ed3\u675f\u751f\u547d",
    "\u4f24\u5bb3\u81ea\u5df1",
    "\u4f24\u5bb3\u522b\u4eba",
    "\u8df3\u4e0b\u53bb",
    "\u9057\u4e66",
    "\u624b\u8fb9\u6709\u5200",
    "\u836f\u4e00\u6b21\u6027\u5168\u5403",
    "suicide",
    "kill myself",
    "self harm",
]

RISK_TREND_TERMS = [
    "\u770b\u4e0d\u5230\u4ee5\u540e",
    "\u6491\u4e0d\u4e0b\u53bb",
    "\u6ca1\u6709\u610f\u4e49",
    "\u6d88\u5931",
    "\u7edd\u671b",
    "\u5d29\u6e83",
    "\u4e0d\u7528\u518d\u9ebb\u70e6",
    "\u63a7\u5236\u4e0d\u4f4f",
]

CONSULT_TREND_TERMS = [
    "\u538b\u529b",
    "\u7126\u8651",
    "\u5931\u7720",
    "\u7761\u4e0d\u7740",
    "\u60c5\u7eea\u4f4e\u843d",
    "\u6291\u90c1",
    "\u5b64\u72ec",
    "\u96be\u8fc7",
    "\u65e0\u52a9",
    "\u5fc3\u7406\u54a8\u8be2",
    "\u6ca1\u6709\u52a8\u529b",
    "\u80f8\u95f7",
    "\u624b\u6296",
]


class VerificationBand(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    UPGRADE = "UPGRADE"


@dataclass(frozen=True)
class SafetyVerificationResult:
    original_intent: IntentType
    verified_intent: IntentType
    risk_similarity: float
    consult_similarity: float
    risk_trend_score: float
    consult_trend_score: float
    strong_risk_score: float
    final_risk_score: float
    final_consult_score: float
    matched_prototype: str
    decision_band: VerificationBand
    upgraded: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "originalIntent": self.original_intent.value,
            "verifiedIntent": self.verified_intent.value,
            "riskSimilarity": round(self.risk_similarity, 4),
            "consultSimilarity": round(self.consult_similarity, 4),
            "riskTrendScore": round(self.risk_trend_score, 4),
            "consultTrendScore": round(self.consult_trend_score, 4),
            "strongRiskScore": round(self.strong_risk_score, 4),
            "finalRiskScore": round(self.final_risk_score, 4),
            "finalConsultScore": round(self.final_consult_score, 4),
            "matchedPrototype": self.matched_prototype,
            "decisionBand": self.decision_band.value,
            "upgraded": self.upgraded,
            "reason": self.reason,
        }


class SafetyVerifierService:
    """Risk recall guard for implicit safety/support signals.

    This verifier is intentionally conservative: it may upgrade an intent
    from CHAT to CONSULT/RISK, or CONSULT to RISK, but it never downgrades a
    previous RISK decision. It uses local evidence only, so the route does not
    add another LLM call before streaming begins.
    """

    def __init__(
        self,
        risk_upgrade_threshold: float = 0.42,
        risk_watch_threshold: float = 0.28,
        consult_upgrade_threshold: float = 0.30,
        consult_watch_threshold: float = 0.20,
    ):
        self.risk_upgrade_threshold = risk_upgrade_threshold
        self.risk_watch_threshold = risk_watch_threshold
        self.consult_upgrade_threshold = consult_upgrade_threshold
        self.consult_watch_threshold = consult_watch_threshold

    def verify(
        self,
        current_input: str,
        memory_brief: str,
        recent_history: list[AiMessage],
        original_intent: IntentType,
    ) -> SafetyVerificationResult:
        text = self._combined_text(current_input, memory_brief, recent_history)
        current = current_input or ""

        risk_similarity, risk_proto = self._best_match(text, RISK_PROTOTYPES)
        consult_similarity, consult_proto = self._best_match(text, CONSULT_PROTOTYPES)
        risk_trend = self._trend_score(text, RISK_TREND_TERMS)
        consult_trend = self._trend_score(text, CONSULT_TREND_TERMS)
        strong_risk = self._strong_signal_score(current, text)

        final_risk = self._risk_score(risk_similarity, risk_trend, strong_risk)
        final_consult = self._consult_score(consult_similarity, consult_trend, risk_trend)

        verified = original_intent
        matched = risk_proto if final_risk >= final_consult else consult_proto
        band = VerificationBand.CLEAR
        reason = "kept original intent"

        if original_intent == IntentType.RISK:
            verified = IntentType.RISK
            band = VerificationBand.UPGRADE
            reason = "kept upstream risk decision"
        elif final_risk >= self.risk_upgrade_threshold:
            verified = IntentType.RISK
            matched = risk_proto
            band = VerificationBand.UPGRADE
            reason = "upgraded by risk prototype, trend, or strong signal"
        elif original_intent == IntentType.CHAT and final_consult >= self.consult_upgrade_threshold:
            verified = IntentType.CONSULT
            matched = consult_proto
            band = VerificationBand.UPGRADE
            reason = "upgraded by consult prototype and context trend"
        elif final_risk >= self.risk_watch_threshold or final_consult >= self.consult_watch_threshold:
            band = VerificationBand.WATCH
            reason = "kept original intent with watch-level safety signal"

        return SafetyVerificationResult(
            original_intent=original_intent,
            verified_intent=verified,
            risk_similarity=risk_similarity,
            consult_similarity=consult_similarity,
            risk_trend_score=risk_trend,
            consult_trend_score=consult_trend,
            strong_risk_score=strong_risk,
            final_risk_score=final_risk,
            final_consult_score=final_consult,
            matched_prototype=matched,
            decision_band=band,
            upgraded=verified != original_intent,
            reason=reason,
        )

    def _combined_text(self, current_input: str, memory_brief: str, recent_history: list[AiMessage]) -> str:
        history_parts = [
            message.content
            for message in recent_history[-6:]
            if str(message.role).lower() not in {"system", "messagerole.system"} and message.content
        ]
        return "\n".join([current_input or "", memory_brief or "", *history_parts])[:3000]

    def _best_match(self, text: str, prototypes: list[str]) -> tuple[float, str]:
        best_score = 0.0
        best_prototype = ""
        for prototype in prototypes:
            score = self._similarity(text, prototype)
            if score > best_score:
                best_score = score
                best_prototype = prototype
        return best_score, best_prototype

    def _strong_signal_score(self, current_input: str, combined_text: str) -> float:
        if self._contains_any(current_input, RISK_STRONG_TERMS):
            return 1.0
        return 0.5 if self._contains_any(combined_text, RISK_STRONG_TERMS) else 0.0

    @staticmethod
    def _risk_score(similarity: float, trend_score: float, strong_score: float) -> float:
        return min(1.0, similarity * 0.55 + trend_score * 0.25 + strong_score * 0.20)

    @staticmethod
    def _consult_score(similarity: float, consult_trend: float, risk_trend: float) -> float:
        return min(1.0, similarity * 0.65 + consult_trend * 0.25 + risk_trend * 0.10)

    @staticmethod
    def _trend_score(text: str, terms: list[str]) -> float:
        if not terms:
            return 0.0
        lower = text.lower()
        hits = sum(1 for term in terms if term.lower() in lower)
        return min(1.0, hits / 3)

    @staticmethod
    def _contains_any(text: str, terms: list[str]) -> bool:
        lower = (text or "").lower()
        return any(term.lower() in lower for term in terms)

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        return token_cosine(left, right) * 0.75 + keyword_score(right, left) * 0.25
