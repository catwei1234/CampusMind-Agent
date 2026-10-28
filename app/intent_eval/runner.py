from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.agents.runtime import AgentRuntimeService
from app.core.config import get_settings
from app.core.enums import IntentType
from app.services.ai import AiClient


LABELS = [IntentType.CHAT.value, IntentType.CONSULT.value, IntentType.RISK.value]
DATASET_PATH = Path("app/intent_eval/intent-eval.json")
OUTPUT_PATH = Path("target/intent-eval-report.json")


def evaluate() -> dict:
    settings = get_settings()
    runtime = AgentRuntimeService.__new__(AgentRuntimeService)
    runtime.ai = AiClient(settings)
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    results = [evaluate_case(runtime, case) for case in cases]
    report = build_report(results, settings)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def evaluate_case(runtime: AgentRuntimeService, case: dict) -> dict:
    expected = case["expectedIntent"]
    predicted = runtime._classify(case["text"], []).value
    return {
        "id": case["id"],
        "text": case["text"],
        "expectedIntent": expected,
        "predictedIntent": predicted,
        "correct": expected == predicted,
    }


def build_report(results: list[dict], settings) -> dict:
    total = max(1, len(results))
    correct = sum(1 for item in results if item["correct"])
    by_label = {}
    for label in LABELS:
        tp = sum(1 for item in results if item["expectedIntent"] == label and item["predictedIntent"] == label)
        fp = sum(1 for item in results if item["expectedIntent"] != label and item["predictedIntent"] == label)
        fn = sum(1 for item in results if item["expectedIntent"] == label and item["predictedIntent"] != label)
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        by_label[label] = {
            "precision": precision,
            "recall": recall,
            "f1": safe_div(2 * precision * recall, precision + recall),
            "support": sum(1 for item in results if item["expectedIntent"] == label),
        }
    confusion = {
        expected: {
            predicted: sum(
                1 for item in results
                if item["expectedIntent"] == expected and item["predictedIntent"] == predicted
            )
            for predicted in LABELS
        }
        for expected in LABELS
    }
    return {
        "createdAt": datetime.utcnow().isoformat(),
        "dataset": str(DATASET_PATH),
        "provider": settings.ai_provider,
        "model": model_name(settings),
        "totalCases": len(results),
        "accuracy": correct / total,
        "macroF1": sum(item["f1"] for item in by_label.values()) / len(LABELS),
        "riskRecall": by_label[IntentType.RISK.value]["recall"],
        "labelMetrics": by_label,
        "confusionMatrix": confusion,
        "predictedDistribution": dict(Counter(item["predictedIntent"] for item in results)),
        "results": results,
    }


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def model_name(settings) -> str:
    provider = settings.ai_provider.lower()
    if provider == "openai":
        return settings.openai_model
    if provider == "ollama":
        return settings.ollama_model
    return "mock"


if __name__ == "__main__":
    report = evaluate()
    print("Intent evaluation completed.")
    for key in ["totalCases", "accuracy", "macroF1", "riskRecall"]:
        print(f"{key}={report[key]}")
    print("labelMetrics=" + json.dumps(report["labelMetrics"], ensure_ascii=False))
    print("confusionMatrix=" + json.dumps(report["confusionMatrix"], ensure_ascii=False))
