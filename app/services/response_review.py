from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import RiskLevel
from app.services.skills import MindBridgeSkill


@dataclass(frozen=True)
class ResponseReview:
    valid: bool
    decision: str
    requires_escalation: bool
    finding_codes: tuple[str, ...]
    checked_skills: tuple[str, ...]

    def to_payload(self) -> dict:
        return {
            "valid": self.valid,
            "decision": self.decision,
            "requiresEscalation": self.requires_escalation,
            "findingCodes": list(self.finding_codes),
            "checkedSkills": list(self.checked_skills),
        }


class ResponseReviewer:
    """Deterministic final-output audit; never sends response content to another model."""

    @staticmethod
    def review(
        output: str,
        skills: list[MindBridgeSkill],
        risk: RiskLevel,
        post_processor_issues: list[str] | None = None,
    ) -> ResponseReview:
        normalized = output.strip()
        findings: list[str] = []
        if not normalized:
            findings.append("EMPTY_OUTPUT")
        for skill in skills:
            schema = skill.output_schema or {}
            minimum = int(schema.get("minLength", 0))
            maximum = int(schema.get("maxLength", 0))
            if minimum and len(normalized) < minimum:
                findings.append(f"MIN_LENGTH:{skill.name}")
            if maximum and len(normalized) > maximum:
                findings.append(f"MAX_LENGTH:{skill.name}")
            if any(term not in normalized for term in schema.get("requiredTerms", [])):
                findings.append(f"MISSING_REQUIRED_TERM:{skill.name}")
            if any(term in normalized for term in schema.get("forbiddenTerms", [])):
                findings.append(f"FORBIDDEN_TERM:{skill.name}")
            question_limit = schema.get("maxQuestions")
            if question_limit is not None and _question_count(normalized) > int(question_limit):
                findings.append(f"MAX_QUESTIONS:{skill.name}")
        if post_processor_issues:
            findings.append("POST_PROCESSOR_ISSUE")
        findings.extend(_safety_findings(normalized, risk))
        unique_findings = tuple(dict.fromkeys(findings))
        valid = not unique_findings
        return ResponseReview(
            valid=valid,
            decision="PASS" if valid else "FLAG",
            requires_escalation=not valid and risk == RiskLevel.HIGH,
            finding_codes=unique_findings,
            checked_skills=tuple(f"{skill.name}@{skill.version}" for skill in skills),
        )

def _safety_findings(text: str, risk: RiskLevel) -> list[str]:
    findings = []
    if _contains_any(text, ["你的风险等级", "风险等级是", "心理报告分数", "后台标签"]):
        findings.append("EXPOSED_INTERNAL_RISK_LABEL")
    if _contains_any(text, ["我确诊你", "你已经确诊", "你就是抑郁症"]):
        findings.append("DIAGNOSIS_CLAIM")
    if _contains_any(text, ["保证绝对保密", "我不会告诉任何人"]):
        findings.append("UNSAFE_CONFIDENTIALITY_PROMISE")
    if risk == RiskLevel.HIGH:
        if not _contains_any(text, ["联系", "求助", "辅导员", "心理中心", "可信任的人", "紧急"]):
            findings.append("HIGH_RISK_MISSING_HELP_SEEKING")
        if _contains_any(text, ["具体方法", "剂量", "买药", "跳楼地点", "割哪里"]):
            findings.append("DANGEROUS_DETAIL")
    return findings


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _question_count(text: str) -> int:
    return text.count("?") + text.count("？")
