# CampusMind-Agent RAG 流程与指标说明

这份文档用于复习 `KnowledgeAgent` 的 RAG 检索流程，以及面试中常被问到的召回、融合、重排序和评测指标。

## 1. RAG 在项目里做什么

`KnowledgeAgent` 是项目里的 RAG 检索节点，只在 `CONSULT / RISK` 场景执行。普通 `CHAT` 不走 RAG。

整体作用：

```text
把用户心理咨询或风险表达
  ↓
改写成适合检索的 query
  ↓
从校园心理知识库召回相关知识
  ↓
把检索结果写入 AgentContext
  ↓
交给 CounselorAgent 生成心理支持回复
```

关键代码：

| 模块 | 位置 | 作用 |
|---|---|---|
| KnowledgeAgent 入口 | `app/agents/runtime.py` | `knowledge_agent()` |
| Query 改写 | `app/agents/runtime.py` | `_rewrite_query()` |
| RAG 检索服务 | `app/services/knowledge.py` | `KnowledgeService.retrieve()` |
| Chroma 向量库 | `app/services/vector_store.py` | `ChromaKnowledgeStore` |
| 配置项 | `app/core/config.py` | topK、candidateK、权重、embedding 模型 |

## 2. 完整 RAG 流程

```text
SupervisorAgent 判断为 CONSULT / RISK
  ↓
controller 调度 KnowledgeAgent
  ↓
KnowledgeAgent 读取 AgentContext
  ↓
结合 memory_brief + 当前输入，改写检索 query
  ↓
调用 KnowledgeService.retrieve(query, top_k=4)
  ↓
从 MySQL 读取知识库 chunks
  ↓
Chroma 向量召回最多 16 个候选
  ↓
BM25 关键词召回最多 16 个候选
  ↓
两路候选合并去重
  ↓
向量分数和 BM25 分数分别归一化
  ↓
按 0.65 / 0.35 加权融合，得到 base_score
  ↓
结合词面相似度、query token 覆盖率、短语命中做本地 rerank
  ↓
取 Top4 结果
  ↓
扩展 Top1 相邻 chunk 上下文
  ↓
写入 AgentContext.knowledge_query 和 retrieved_knowledge
  ↓
后续交给 RiskGuardianAgent / CounselorAgent 使用
```

## 3. Query 改写

`KnowledgeAgent` 不一定直接拿用户原话检索，而是先做 query rewrite。

输入：

```text
memory_brief
+
当前用户输入 model_input
```

输出：

```text
适合检索校园心理知识库的 query
```

如果 LLM 改写失败，则使用原始 `model_input` 兜底。

面试说法：

> Query rewrite 的目的是把用户自然表达改成更适合知识库检索的查询词，比如把“我晚上一直睡不好，白天也没精神”改写成“失眠 睡眠质量 压力调节”。这样可以提升 RAG 召回的稳定性。

## 4. 知识库如何入库

知识库文件在：

```text
app/knowledge/
```

入库时会切成 chunk：

```text
knowledge_chunk_size = 512
knowledge_chunk_overlap = 64
```

也就是：

```text
每个知识片段约 512 字符
相邻片段重叠 64 字符
```

切片后：

```text
1. 存入 MySQL 的 knowledge_chunks 表
2. 如果向量检索可用，生成 embedding 并写入 Chroma
```

## 5. Embedding 和 Chroma

默认 embedding 模型：

```text
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

注意分工：

```text
Embedding 模型：把文本转成向量
Chroma：保存向量，并根据向量相似度做检索
```

Chroma 不是 embedding 模型，它是向量数据库。

如果使用 DeepSeek：

```text
DeepSeek 主要负责聊天生成
不一定支持 /embeddings
如果 embeddings 不可用，项目会降级到 BM25 + 本地 rerank
```

## 6. 16 个候选怎么来的

配置：

```text
knowledge_top_k = 4
knowledge_candidate_k = 16
```

含义：

```text
最终返回 Top4
但排序前先扩大召回池，每路最多召回 16 个候选
```

两路召回：

```text
query
  ├─ Chroma 向量召回最多 16 个候选
  └─ BM25 关键词召回最多 16 个候选
```

然后合并去重。

一个 chunk 合并后可能有三种情况：

| 命中情况 | vector_score | bm25_score |
|---|---:|---:|
| 只被向量召回 | 有 | 0 |
| 只被 BM25 召回 | 0 | 有 |
| 两路都召回 | 有 | 有 |

所以不是每个 chunk 都一定有两个分数，而是最多有两个分数。

## 7. 向量召回分数

向量召回流程：

```text
query 文本
  ↓
embedding 模型转成 query_embedding
  ↓
Chroma 根据 query_embedding 查询相似 chunk
  ↓
返回 chunk 和 distance
  ↓
项目把 distance 转成 score
```

项目中 Chroma 使用 cosine space：

```text
hnsw:space = cosine
```

分数转换：

```text
vector_score = 1 / (1 + distance)
```

理解：

```text
distance 越小
说明 query 和 chunk 越相似
vector_score 越高
```

## 8. BM25 召回分数

BM25 是传统关键词检索算法，主要考虑：

```text
query 词是否出现在 chunk 中
词出现频率
词在整个知识库里是否稀有
chunk 长度归一化
```

适合命中明确关键词，比如：

```text
失眠
焦虑
考试压力
心理咨询
人际关系
```

项目里的中文分词逻辑会保留：

```text
英文 / 数字 token
中文单字
中文 bigram
```

例如：

```text
考试焦虑
```

会产生类似：

```text
考、试、焦、虑、考试、试焦、焦虑
```

这样可以增强中文关键词召回效果。

## 9. 分数融合

因为向量分数和 BM25 分数来源不同，不能直接相加，所以项目先归一化：

```text
normalized_vector_score
normalized_bm25_score
```

然后加权融合：

```text
base_score =
  normalized_vector_score * 0.65
  +
  normalized_bm25_score * 0.35
```

如果某个 chunk 只被一路召回，另一路分数为 0。

面试说法：

> 向量召回和 BM25 是并行两路召回。合并去重后，如果某个 chunk 只被一路命中，另一路分数就是 0；如果两路都命中，就同时拥有语义分数和关键词分数。项目会先对两路分数归一化，再按 0.65 / 0.35 加权融合得到 `base_score`。

## 10. 本地 Rerank 怎么算

融合分数 `base_score` 还不是最终排序分数，它会继续进入本地 rerank。

最终公式：

```text
rerank_score =
  base_score * 0.55
  + lexical * 0.25
  + coverage * 0.15
  + phrase * 0.05
```

四个特征：

| 特征 | 权重 | 含义 |
|---|---:|---|
| `base_score` | 0.55 | 向量分数和 BM25 分数融合后的基础分 |
| `lexical` | 0.25 | 词面相似度，结合 token cosine 和关键词命中 |
| `coverage` | 0.15 | query 里的 token 有多少被 chunk 覆盖 |
| `phrase` | 0.05 | query 短语是否完整出现在 chunk 中 |

`lexical` 的计算：

```text
lexical =
  token_cosine(query, chunk) * 0.75
  +
  keyword_score(query, chunk) * 0.25
```

理解：

```text
base_score 保留混合召回排序结果
lexical 提升词面相似内容
coverage 提升覆盖 query 关键词更多的内容
phrase 提升完整短语命中的内容
```

面试说法：

> 重排序不是再调用一个 rerank 大模型，而是本地确定性 rerank。项目先用向量和 BM25 融合得到 `base_score`，再额外计算词面相似度、query token 覆盖率和短语命中，按 0.55 / 0.25 / 0.15 / 0.05 加权得到最终 `rerank_score`。这样成本低、可解释，也不依赖额外 rerank 服务。

## 11. Top1 为什么扩展相邻 chunk

知识库是切片存储的，一个 chunk 可能上下文不完整。

所以最终返回前会对 Top1 做扩展：

```text
Top1 前一个 chunk
+
Top1 chunk
+
Top1 后一个 chunk
```

好处：

```text
补足上下文
减少断章取义
提升回答完整性
```

## 12. RAG 评测结果

当前 RAG 评测结果：

```text
totalCases = 60
topK = 4
Recall@4 = 96.7%
Precision@4 = 64.6%
MRR = 90.8%
NDCG@4 = 90.5%
HitRate@4 = 96.7%
AverageFirstRelevantRank = 1.16
```

简历建议重点写：

```text
Recall@4 96.7%
HitRate@4 96.7%
MRR 90.8%
NDCG@4 90.5%
```

## 13. 四个核心评测指标是什么

### 13.1 Recall@4

含义：

```text
Top4 里召回了多少应该召回的正确知识
```

它关注的是“有没有漏掉正确答案”。

公式简化：

```text
Recall@4 = Top4 中命中的相关文档数 / 该 query 应该命中的相关文档总数
```

例子：

```text
某个 query 标注了 2 个相关 chunk
Top4 命中了其中 2 个
Recall@4 = 2 / 2 = 1.0
```

如果只命中 1 个：

```text
Recall@4 = 1 / 2 = 0.5
```

### 13.2 HitRate@4

含义：

```text
Top4 里是否至少命中一个正确知识
```

它是 query 级别的命中率。

公式简化：

```text
HitRate@4 = 至少命中一个相关文档的 query 数 / 总 query 数
```

例子：

```text
60 条测试问题里，有 58 条 Top4 至少命中一个正确 chunk
HitRate@4 = 58 / 60 = 96.7%
```

### 13.3 MRR

MRR 全称是 Mean Reciprocal Rank，平均倒数排名。

含义：

```text
第一个正确结果排得越靠前，MRR 越高
```

单条 query 的分数：

```text
第一个正确结果排第 1 位 -> 1 / 1 = 1.0
第一个正确结果排第 2 位 -> 1 / 2 = 0.5
第一个正确结果排第 3 位 -> 1 / 3 = 0.333
TopK 内没有正确结果 -> 0
```

MRR 就是所有 query 的平均值。

你的结果：

```text
MRR = 90.8%
```

说明大多数 query 的第一个正确知识都排在很靠前的位置。

### 13.4 NDCG@4

NDCG 全称是 Normalized Discounted Cumulative Gain。

含义：

```text
不仅看有没有命中，还看正确结果排得好不好
```

越相关的内容排越靠前，NDCG 越高。

直观理解：

```text
正确结果排第 1 位，收益最大
正确结果排第 2 位，收益打折
正确结果排第 3、4 位，收益继续降低
```

NDCG@4 会把当前排序和“理想排序”做对比，范围通常是：

```text
0 ~ 1
```

你的结果：

```text
NDCG@4 = 90.5%
```

说明 Top4 里相关知识不仅能召回，而且排序质量比较好。

## 14. 面试完整回答

> 我项目里的 RAG 由 KnowledgeAgent 负责，只在咨询和风险场景执行。流程上先结合用户输入和 MemoryAgent 生成的记忆摘要做 query rewrite，然后进入 `KnowledgeService.retrieve()`。知识库提前按 512 字符切片、64 字符重叠，存入 MySQL；如果向量检索可用，会用 `text-embedding-3-small` 生成向量并写入 Chroma。检索时同时走 Chroma 向量召回和 BM25 关键词召回，两路各取最多 16 个候选，合并去重后分别归一化向量分数和 BM25 分数，再按 0.65 / 0.35 加权融合得到 `base_score`。之后本地 rerank 会综合 `base_score`、词面相似度、query token 覆盖率和短语命中，最终取 Top4，并扩展 Top1 相邻 chunk 补足上下文。评测上我用 Recall@4、HitRate@4、MRR 和 NDCG@4 衡量召回和排序质量。

## 15. 简历可用表达

> 构建校园心理健康知识库，基于 Chroma 向量召回与 BM25 关键词召回实现混合检索，两路各召回 16 个候选后进行分数归一化、0.65 / 0.35 加权融合，并结合词面相似度、query 覆盖率和短语命中做本地 rerank，最终返回 Top4；在 60 条自建 RAG 样例上达到 Recall@4 96.7%、HitRate@4 96.7%、MRR 90.8%、NDCG@4 90.5%。
