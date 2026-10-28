# Agent Safety And RAG Enhancement Plan

This note records the project enhancements that are easiest to explain in
interviews and useful for a second-development version of CampusMind-Agent.

## 1. RiskRecallGuard / SafetyVerifierAgent

Goal: reduce missed routing for implicit psychological risk without adding a
second LLM call before SSE streaming.

Current flow:

```text
SupervisorAgent routes CHAT / CONSULT / RISK
  -> SafetyVerifierAgent reads current input, recent history, memory brief
  -> compares them with RISK / CONSULT prototypes
  -> scores context trend and strong risk signals
  -> only upgrades intent, never downgrades it
```

Implemented logic:

- risk and consult prototype similarity
- recent history and long-term memory trend score
- strong high-risk signal score
- double thresholds:
  - `UPGRADE`: upgrade CHAT/CONSULT to a safer route
  - `WATCH`: keep original route but record a watch-level safety signal
- monotonic safety rule:
  - `CHAT -> CONSULT`
  - `CHAT -> RISK`
  - `CONSULT -> RISK`
  - never `RISK -> CONSULT/CHAT`

Code:

- `app/services/safety_verifier.py`
- `app/agents/runtime.py::safety_verifier_agent`
- `app/agents/langgraph_runtime.py::_safety_verifier_node`
- `tests/test_safety_verifier.py`

Trace fields:

- `originalIntent`
- `verifiedIntent`
- `riskSimilarity`
- `consultSimilarity`
- `riskTrendScore`
- `consultTrendScore`
- `strongRiskScore`
- `finalRiskScore`
- `finalConsultScore`
- `decisionBand`
- `upgraded`
- `reason`

Interview wording:

> I added a RiskRecallGuard after SupervisorAgent. Instead of simply calling
> the LLM again, it combines current input, recent history and long-term memory
> summary, then computes risk prototype similarity, consult prototype
> similarity, negative-trend signals and strong high-risk signals. It uses
> double thresholds for watch and upgrade decisions, and only upgrades intent,
> never downgrades a RISK decision. This improves recall for implicit risk while
> keeping the streaming path fast and deterministic.

## 2. Structured RAG Chunking

Goal: improve retrieval quality and explainability by using document structure,
not only fixed-size chunks.

Implemented flow:

```text
Read Markdown document
  -> split by heading hierarchy
  -> split oversized sections by paragraph/list boundary
  -> keep overlap between adjacent chunks
  -> store source, heading_path, chunk_index metadata
  -> embed heading_path + content
```

Code:

- `app/services/chunking.py`
- `app/services/knowledge.py::KnowledgeService._chunk_source`
- `app/core/config.py::knowledge_chunk_strategy`

The current implementation keeps database compatibility by prefixing each
structured chunk with `Source` and `Section` instead of adding new database
columns. This avoids migration risk while still allowing the embedding and BM25
paths to use heading context.

Interview wording:

> I plan to replace pure fixed-size chunking with structure-aware Markdown
> chunking. The splitter first respects heading, paragraph and list boundaries,
> then applies length and overlap constraints only when a section is too large.
> Each chunk keeps its heading path as metadata, so retrieval has better
> semantic context and Trace can explain exactly which section supported the
> answer.

## 3. Evaluation Loop

Goal: make intent routing and RAG improvements measurable.

Intent evaluation:

- dataset: `input`, `expected_intent`
- metrics:
  - Accuracy
  - Macro-F1
  - RISK Recall
  - CONSULT Recall
  - confusion matrix

RAG evaluation:

- dataset: `query`, `expected_sources`, `expected_sections`
- metrics:
  - Recall@4
  - HitRate@4
  - MRR
- NDCG@4

Implemented RAG ablations:

- fixed chunking vs structured chunking
- Top3 / Top4 / Top5
- rerank enabled vs disabled

Command:

```powershell
.\.conda\python.exe -m app.rag_eval.runner --ablations
```

Report:

```text
target/rag-eval-ablation-report.json
```

Interview wording:

> I do not only rely on subjective testing. I build small evaluation sets for
> intent routing and RAG retrieval, then compare chunking strategies, recall
> strategies and TopK choices with Accuracy, RISK Recall, Recall@4, MRR and
> NDCG@4.

## 4. ResponseReviewerAgent

Goal: audit generated replies after streaming output is produced.

Checks:

- empty or too short output
- output schema violations from selected Skills
- exposed internal risk labels or report scores
- diagnosis-like statements
- unsafe confidentiality promises
- high-risk replies missing help-seeking guidance
- dangerous details in high-risk replies

Code:

- `app/services/response_review.py`
- `app/services/chat.py`

Interview wording:

> I enhanced the response review stage as a ResponseReviewerAgent. After the
> assistant response is generated, it runs deterministic safety checks against
> the selected Skills and risk level. For high-risk responses, it requires
> help-seeking guidance and blocks dangerous details or internal risk labels.

## 5. RAG Evidence Constraint

Goal: make retrieved knowledge auditable and reduce hallucination.

Flow:

```text
KnowledgeAgent retrieves Top4 chunks
  -> context builder formats them as [E1], [E2] evidence blocks
  -> each evidence block carries source and score
  -> Trace records evidence id, chunk id, source, score and preview
  -> CounselorAgent receives evidence-aware context
```

Code:

- `app/services/context_builder.py::_format_knowledge_evidence`
- `app/agents/runtime.py::_capture_context_snapshot`

Interview wording:

> I strengthened RAG evidence constraints by formatting retrieved chunks as
> evidence blocks with source and score, and by writing the same evidence
> metadata into Agent Trace. This makes it clear which knowledge chunks
> supported the response and helps reduce unsupported campus-policy
> hallucination.
