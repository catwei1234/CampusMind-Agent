# RAG Structured Chunking And Ablation

This note records the RAG optimization implemented in the second-development
version of CampusMind-Agent.

## 1. What Changed

The original knowledge ingestion used fixed-size chunks:

```text
raw markdown
  -> normalize whitespace
  -> split every knowledge_chunk_size chars
  -> keep knowledge_chunk_overlap chars
```

The new default strategy is structure-aware chunking:

```text
raw markdown
  -> split by Markdown heading hierarchy
  -> keep heading_path
  -> split oversized sections by paragraph/list boundary
  -> keep overlap between adjacent chunks
  -> prefix chunk content with Source and Section
```

Code:

- `app/services/chunking.py`
- `app/services/knowledge.py::KnowledgeService._chunk_source`
- `app/core/config.py::knowledge_chunk_strategy`

Default config:

```text
knowledge_chunk_strategy = "structured"
knowledge_chunk_size = 512
knowledge_chunk_overlap = 64
```

## 2. Why It Helps

Campus mental-health knowledge documents are naturally structured:

```text
Sleep
  -> Hard to fall asleep
  -> What students can try
Academic stress
  -> Exam anxiety
  -> Planning steps
```

Fixed-size splitting can cut across a title, explanation and advice list. The
structured splitter keeps the section title with the body, so retrieval can use
both the semantic heading and the actual advice text.

Example chunk:

```text
Source: sleep.md
Section: Sleep > Hard to fall asleep

Keep a fixed wake-up time.
- Reduce screen time.
- Try breathing practice.
```

## 3. Ablation Evaluation

Command:

```powershell
.\.conda\python.exe -m app.rag_eval.runner --ablations
```

The ablation runner uses temporary in-memory SQLite databases, so it does not
modify the main MySQL/SQLite project database. Vector retrieval is disabled in
ablation mode to isolate chunking, TopK and local rerank effects.

Implemented experiments:

- fixed chunks + Top4 + rerank
- structured chunks + Top4 + rerank
- structured chunks + Top4 + no rerank
- structured chunks + Top3 + rerank
- structured chunks + Top5 + rerank

Report path:

```text
target/rag-eval-ablation-report.json
```

## 4. Current Result

On the current RAG evaluation dataset:

| Experiment | Recall@K | MRR | NDCG@K | Avg Retrieved Chars |
|---|---:|---:|---:|---:|
| fixed_top4_rerank | 96.67% | 90.83% | 90.53% | 2679.3 |
| structured_top4_rerank | 100.00% | 94.44% | 94.04% | 1940.3 |
| structured_top4_no_rerank | 100.00% | 93.61% | 94.00% | 1947.9 |
| structured_top3_rerank | 100.00% | 94.44% | 95.09% | 1622.5 |
| structured_top5_rerank | 100.00% | 94.44% | 92.87% | 2259.4 |

Takeaway:

- structured chunking improved recall and ranking quality over fixed chunks
- structured Top3 achieved the best NDCG and lowest context cost in this local
  ablation
- Top4 remains a safe product default because it leaves more context margin
  while still keeping average retrieved chars lower than fixed chunks

## 5. Interview Wording

> I optimized the RAG ingestion pipeline from fixed-size splitting to
> structure-aware Markdown chunking. The splitter first follows heading
> hierarchy and paragraph/list boundaries, then applies length and overlap
> constraints only when a section is too large. Each chunk keeps Source and
> Section metadata in the retrieval text, which improves semantic recall and
> makes Trace evidence easier to explain.

> I also added an ablation runner for RAG. It compares fixed chunking vs
> structured chunking, Top3/Top4/Top5 and rerank on/off, and reports Recall@K,
> MRR, NDCG@K and average retrieved context length. In the current dataset,
> structured Top4 improved Recall@K from 96.67% to 100% and MRR from 90.83% to
> 94.44%, while reducing average retrieved context length.
