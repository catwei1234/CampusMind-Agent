import argparse
import json
import math
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import create_schema, seed_data
from app.core.config import Settings, get_settings
from app.core.database import Base, SessionLocal
from app.services.knowledge import KnowledgeService


def evaluate() -> dict:
    settings = get_settings()
    create_schema()
    db = SessionLocal()
    try:
        seed_data(db)
        service = KnowledgeService(db, settings)
        cases = load_cases(settings)
        results = [evaluate_case(service, case, settings.knowledge_top_k) for case in cases]
        report = build_report(settings, results, settings.knowledge_top_k)
        output = Path(settings.rag_eval_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        db.close()


def evaluate_ablations() -> dict:
    base_settings = get_settings()
    cases = load_cases(base_settings)
    experiments = [
        {
            "name": "fixed_top4_rerank",
            "description": "Fixed-size chunks, BM25 recall, local rerank, Top4.",
            "updates": {"knowledge_chunk_strategy": "fixed", "knowledge_top_k": 4, "knowledge_rerank_enabled": True},
        },
        {
            "name": "structured_top4_rerank",
            "description": "Markdown structure chunks, BM25 recall, local rerank, Top4.",
            "updates": {"knowledge_chunk_strategy": "structured", "knowledge_top_k": 4, "knowledge_rerank_enabled": True},
        },
        {
            "name": "structured_top4_no_rerank",
            "description": "Markdown structure chunks, BM25 recall, no rerank, Top4.",
            "updates": {"knowledge_chunk_strategy": "structured", "knowledge_top_k": 4, "knowledge_rerank_enabled": False},
        },
        {
            "name": "structured_top3_rerank",
            "description": "Markdown structure chunks, BM25 recall, local rerank, Top3.",
            "updates": {"knowledge_chunk_strategy": "structured", "knowledge_top_k": 3, "knowledge_rerank_enabled": True},
        },
        {
            "name": "structured_top5_rerank",
            "description": "Markdown structure chunks, BM25 recall, local rerank, Top5.",
            "updates": {"knowledge_chunk_strategy": "structured", "knowledge_top_k": 5, "knowledge_rerank_enabled": True},
        },
    ]
    reports = []
    for experiment in experiments:
        settings = ablation_settings(base_settings, experiment["updates"])
        report = evaluate_with_temp_db(settings, cases)
        reports.append({
            "name": experiment["name"],
            "description": experiment["description"],
            "settings": {
                "chunkStrategy": settings.knowledge_chunk_strategy,
                "topK": settings.knowledge_top_k,
                "rerankEnabled": settings.knowledge_rerank_enabled,
                "vectorEnabled": settings.knowledge_vector_enabled,
            },
            "metrics": compact_metrics(report),
            "results": report["results"],
        })

    best = max(reports, key=lambda item: (item["metrics"]["mrr"], item["metrics"]["recallAtK"], item["metrics"]["ndcgAtK"]))
    output = Path(base_settings.rag_eval_output).with_name("rag-eval-ablation-report.json")
    final_report = {
        "createdAt": datetime.utcnow().isoformat(),
        "dataset": base_settings.rag_eval_dataset,
        "note": "Ablations run in temporary SQLite databases with vector retrieval disabled, so this isolates chunking, TopK, and local rerank effects.",
        "bestByMrr": best["name"],
        "experiments": reports,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_report


def evaluate_with_temp_db(settings: Settings, cases: list[dict]) -> dict:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        service = KnowledgeService(db, settings)
        seed_knowledge(service, settings)
        results = [evaluate_case(service, case, settings.knowledge_top_k) for case in cases]
        return build_report(settings, results, settings.knowledge_top_k)
    finally:
        db.close()
        engine.dispose()


def ablation_settings(base: Settings, updates: dict) -> Settings:
    merged = {
        **updates,
        "knowledge_vector_enabled": False,
        "knowledge_vector_required": False,
    }
    return base.model_copy(update=merged)


def seed_knowledge(service: KnowledgeService, settings: Settings) -> None:
    root = settings.project_root / "app" / "knowledge"
    for file in sorted(root.glob("*.md")):
        service.ingest(file.name, file.read_text(encoding="utf-8"))


def load_cases(settings: Settings) -> list[dict]:
    dataset_path = Path(settings.rag_eval_dataset)
    if not dataset_path.is_absolute():
        dataset_path = settings.project_root / dataset_path
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def build_report(settings: Settings, results: list[dict], top_k: int) -> dict:
    total = max(1, len(results))
    hits = [item for item in results if item["hit"]]
    return {
        "createdAt": datetime.utcnow().isoformat(),
        "dataset": settings.rag_eval_dataset,
        "topK": top_k,
        "chunkStrategy": settings.knowledge_chunk_strategy,
        "rerankEnabled": settings.knowledge_rerank_enabled,
        "vectorEnabled": settings.knowledge_vector_enabled,
        "totalCases": len(results),
        "recallAtK": sum(item["recallAtK"] for item in results) / total,
        "precisionAtK": sum(item["precisionAtK"] for item in results) / total,
        "mrr": sum(item["reciprocalRank"] for item in results) / total,
        "ndcgAtK": sum(item["ndcgAtK"] for item in results) / total,
        "hitRate": len(hits) / total,
        "averageFirstRelevantRank": sum(item["firstRelevantRank"] for item in hits) / max(1, len(hits)),
        "averageRetrievedChars": sum(item["retrievedChars"] for item in results) / total,
        "results": results,
    }


def compact_metrics(report: dict) -> dict:
    keys = [
        "totalCases",
        "topK",
        "recallAtK",
        "precisionAtK",
        "mrr",
        "ndcgAtK",
        "hitRate",
        "averageFirstRelevantRank",
        "averageRetrievedChars",
    ]
    return {key: report[key] for key in keys}


def evaluate_case(service: KnowledgeService, case: dict, top_k: int) -> dict:
    retrieved = service.retrieve(case["question"], top_k)
    expected_sources = {source.lower() for source in case.get("expectedSources", [])}
    expected_terms = [term.lower() for term in case.get("expectedTerms", [])]
    items = []
    first_rank = 0
    relevant_count = 0
    retrieved_chars = 0
    for index, item in enumerate(retrieved, start=1):
        retrieved_chars += len(item.content)
        relevant = is_relevant(item.source, item.content, expected_sources, expected_terms)
        if relevant:
            relevant_count += 1
            if first_rank == 0:
                first_rank = index
        items.append({
            "rank": index,
            "chunkId": item.chunk_id,
            "source": item.source,
            "score": item.score,
            "relevant": relevant,
            "preview": " ".join(item.content.split())[:160],
        })
    hit = first_rank > 0
    return {
        "id": case["id"],
        "question": case["question"],
        "expectedSources": case.get("expectedSources", []),
        "expectedTerms": case.get("expectedTerms", []),
        "retrieved": items,
        "hit": hit,
        "firstRelevantRank": first_rank,
        "recallAtK": 1.0 if hit else 0.0,
        "precisionAtK": relevant_count / top_k if top_k > 0 else 0.0,
        "reciprocalRank": 1.0 / first_rank if hit else 0.0,
        "ndcgAtK": ndcg(items),
        "retrievedChars": retrieved_chars,
    }


def is_relevant(source: str, content: str, expected_sources: set[str], expected_terms: list[str]) -> bool:
    if source.lower() in expected_sources:
        return True
    lower = content.lower()
    return any(len(term) >= 2 and term in lower for term in expected_terms)


def ndcg(items: list[dict]) -> float:
    dcg = 0.0
    relevant = 0
    for index, item in enumerate(items):
        if item["relevant"]:
            relevant += 1
            dcg += 1.0 / math.log(index + 2.0)
    if relevant == 0:
        return 0.0
    ideal = sum(1.0 / math.log(index + 2.0) for index in range(relevant))
    return dcg / ideal


def print_report(report: dict) -> None:
    print("RAG evaluation completed.")
    for key in [
        "totalCases",
        "topK",
        "chunkStrategy",
        "rerankEnabled",
        "recallAtK",
        "precisionAtK",
        "mrr",
        "ndcgAtK",
        "hitRate",
        "averageFirstRelevantRank",
        "averageRetrievedChars",
    ]:
        print(f"{key}={report[key]}")


def print_ablation_report(report: dict) -> None:
    print("RAG ablation evaluation completed.")
    print(f"bestByMrr={report['bestByMrr']}")
    for experiment in report["experiments"]:
        metrics = experiment["metrics"]
        print(
            f"{experiment['name']}: "
            f"recallAtK={metrics['recallAtK']:.4f}, "
            f"mrr={metrics['mrr']:.4f}, "
            f"ndcgAtK={metrics['ndcgAtK']:.4f}, "
            f"avgChars={metrics['averageRetrievedChars']:.1f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ablations", action="store_true", help="Run chunking/TopK/rerank ablation experiments.")
    args = parser.parse_args()
    if args.ablations:
        print_ablation_report(evaluate_ablations())
    else:
        print_report(evaluate())
