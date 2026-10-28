# CampusMind-Agent 面试问答

## 1. 为什么用 LangGraph？

LangGraph 更适合有状态、多分支、多 Agent 的流程编排。这个项目不是简单的一条 LLM 调用链，而是需要根据用户输入动态进入记忆召回、意图识别、RAG 检索、风险评估、普通回复或心理支持回复等不同节点。

面试回答：

> 我选择 LangGraph 是因为心理支持场景需要明确的状态流转和分支控制。比如普通 CHAT 可以直接由 CompanionAgent 回复，而 CONSULT / RISK 需要进入 RAG 检索和风险评估链路。LangGraph 的 State、Node、Conditional Edge 很适合表达这种多 Agent 状态机，也方便做 Trace 记录和最大步数限制。

## 2. AgentContext 是什么？

`AgentContext` 是项目自定义的一次对话运行时上下文，挂在 LangGraph 的 `GraphState.context` 里面。

它保存：

```text
用户输入
脱敏输入
历史记忆
意图分类
RAG 检索结果
风险评估
最终 prompt messages
Agent 执行步骤
Trace 快照
```

面试回答：

> `AgentContext` 是多 Agent 之间共享状态的数据结构。每个 Agent 执行后都会把结果写入 Context，比如 MemoryAgent 写入记忆，SupervisorAgent 写入意图，KnowledgeAgent 写入检索结果，RiskGuardianAgent 写入风险评估，最终回复 Agent 写入 response messages。这样各 Agent 之间不需要直接强耦合，同时也方便记录 Trace。

## 3. controller 怎么选择下一个 Agent？

controller 会读取 `AgentContext` 里的状态标记来决定下一步。

判断逻辑：

```text
memory_loaded == False -> MemoryAgent
intent_routed == False -> SupervisorAgent
intent == CHAT -> CompanionAgent
knowledge_handled == False -> KnowledgeAgent
risk_assessed == False -> RiskGuardianAgent
response_planned == False -> CounselorAgent
全部完成 -> END
steps >= max_steps -> END
```

面试回答：

> controller 本身不处理业务，只负责调度。它根据 `AgentContext` 中的 `memory_loaded`、`intent_routed`、`knowledge_handled`、`risk_assessed`、`response_planned` 等状态字段选择下一个 Agent。每个 Agent 执行完写回 Context，再回到 controller。为了避免异常循环，系统设置了 `max_steps=8`。

## 4. MemoryAgent 从哪里召回记忆？

MemoryAgent 不是向量召回，而是按用户和会话维度召回。

来源：

```text
Redis：当前会话最近聊天记录和摘要缓存
MySQL：chat_messages 历史消息和 long_term_memory 长期摘要
```

流程：

```text
先按 session_public_id 查 Redis
Redis 没有 -> 按 user_id + session_id 查 MySQL
查到后回填 Redis
```

面试回答：

> MemoryAgent 采用 Redis 优先、MySQL 兜底的分层记忆读取。短期记忆按 `session_public_id` 从 Redis 读取当前会话最近消息；Redis 未命中时，按 `user_id + session_id` 从 MySQL 的 `chat_messages` 回查，并回填 Redis。长期摘要也是先查 Redis summary，没有再查 MySQL 的 `long_term_memory`。

## 5. 长期摘要怎么生成？

长期摘要是每轮 MemoryAgent 运行时更新的 `memory_brief`。

流程：

```text
召回最近聊天记录
  ↓
读取已有长期摘要
  ↓
历史消息脱敏、裁剪
  ↓
生成规则摘要 fallback
  ↓
优先调用 LLM 生成新的 memory_brief
  ↓
LLM 失败则使用 fallback
  ↓
写回 Redis 和 MySQL
```

面试回答：

> 长期摘要优先由 LLM 根据最近历史和当前输入生成，用来总结用户近期关注点和已给过的支持建议。如果 LLM 失败，就使用规则摘要兜底，规则摘要会抽取最近几条用户表达和助手回复并截断拼接。最终摘要按 `user_id + session_id` upsert 到 MySQL 的 `long_term_memory`，同时写入 Redis summary 缓存。

## 6. SupervisorAgent 怎么做 CHAT / CONSULT / RISK 分类？

它采用：

```text
强规则前置 + LLM 三分类 + 弱规则兜底
```

流程：

```text
高风险关键词命中 -> RISK
明确任务型请求 -> CHAT
明显心理咨询表达 -> CONSULT
规则不确定 -> 调用 LLM 返回 CHAT / CONSULT / RISK
LLM 失败 -> 弱咨询规则命中则 CONSULT，否则 CHAT
```

面试回答：

> SupervisorAgent 负责意图路由。它先用高置信规则拦截明确 RISK、任务型 CHAT 和明显 CONSULT；规则无法确定时调用 LLM 做三分类；如果 LLM 不可用，则用弱咨询规则兜底，命中咨询信号判 CONSULT，否则默认 CHAT。分类结果写入 `AgentContext.intent`，controller 再决定后续链路。

## 7. RAG 的 16 个候选怎么来？

`knowledge_candidate_k=16` 表示每路召回最多 16 个候选。

流程：

```text
query
  ├─ Chroma 向量召回最多 16 个
  └─ BM25 关键词召回最多 16 个
```

然后合并去重。

面试回答：

> RAG 不是直接取最终 Top4，而是先扩大候选池。系统会用 Chroma 向量检索召回最多 16 个语义相似 chunk，同时用 BM25 关键词检索召回最多 16 个关键词相关 chunk。两路结果合并去重后再做分数融合和 rerank，最后返回 Top4。

## 8. rerank 是模型还是规则？

当前项目的 rerank 是本地规则 / 特征加权，不是 rerank 模型。

公式：

```text
rerank_score =
  base_score * 0.55
  + lexical * 0.25
  + coverage * 0.15
  + phrase * 0.05
```

含义：

```text
base_score：向量 + BM25 融合分数
lexical：词面相似度
coverage：query token 覆盖率
phrase：短语完整命中
```

面试回答：

> 当前没有接专门的 rerank 模型，而是做了轻量级本地 rerank。系统先融合向量分数和 BM25 分数得到 `base_score`，再结合词面相似度、query 覆盖率和短语命中计算最终排序分数。这种方式成本低、延迟小、可解释。后续知识库变大时可以接入 bge-reranker 这类 cross-encoder 模型。

## 9. Chroma 和 embedding 模型分别是什么？

二者不是一个东西。

```text
embedding 模型：把文本转成向量
Chroma：存储向量，并做向量相似度检索
```

项目默认 embedding：

```text
text-embedding-3-small
```

面试回答：

> Chroma 是向量数据库，不是嵌入模型。embedding 模型负责把知识 chunk 和 query 转成向量，Chroma 负责保存这些向量，并根据向量距离做相似度查询。项目默认使用 `text-embedding-3-small`，但可以替换为 BGE、Qwen embedding 等中文向量模型。

## 10. DeepSeek 能不能做 embedding？

DeepSeek 主要用于聊天生成，不一定支持 OpenAI-compatible 的 `/embeddings`。

面试回答：

> DeepSeek 更适合用作 Chat Model。Embedding 和 Chat Model 是两个不同能力，项目里可以把聊天生成接 DeepSeek，把 embedding 单独接 OpenAI、BGE 或 Qwen embedding。如果 embedding 服务不可用，系统会降级到 BM25 + 本地 rerank，保证知识检索仍然可用。

## 11. RiskGuardianAgent 怎么生成结构化报告？

RiskGuardianAgent 先生成结构化风险评估，Harness 再把评估落成心理报告。

流程：

```text
RiskGuardianAgent
  ↓
PsychologicalAssessmentService.assess()
  ↓
高风险关键词规则
  ↓
LLM JSON 评估
  ↓
heuristic 兜底
  ↓
生成 assessment
  ↓
Harness 创建 PsychologicalReport
```

报告字段：

```text
user_id
session_id
content
intent
emotion
emotion_score
risk_level
confidence
summary
```

面试回答：

> RiskGuardianAgent 会调用风险评估服务生成结构化 assessment，包括情绪标签、情绪分数、风险等级、置信度和摘要。实现上先用高风险关键词兜底，没命中再调用 LLM 输出严格 JSON，并根据 emotionScore 校准风险等级；模型失败时用本地 heuristic。之后 Harness 会把 assessment 写入 `PsychologicalReport`，用于后台报告和工具闭环。

## 12. Skill 是提示词还是工具？

Skill 不是工具，它更像结构化提示词策略包。

包含：

```text
场景描述
回复 workflow
安全规则
allowed_tools 工具权限声明
output_schema 输出约束
```

面试回答：

> Skill 可以理解为结构化提示词策略包，不是工具本身。CounselorAgent 会根据 intent、risk 和用户输入选择合适 Skill，并把 Skill 内容注入最终 system prompt。Skill 里还会声明 `allowed_tools`，用于限制当前场景允许哪些工具被调用。

## 13. MCP 和 Function Call 区别是什么？

简单区分：

```text
Function Call：模型怎么提出要调用哪个函数，以及参数是什么
MCP：外部工具如何被标准化暴露和连接
```

面试回答：

> Function Call 是模型侧的工具调用机制，模型根据用户意图输出函数名和结构化参数，应用程序再执行函数。MCP 是工具连接协议，用来把外部系统能力标准化暴露成工具。可以理解为 Function Call 关注“模型如何发起调用”，MCP 关注“工具如何被统一接入和管理”。

## 14. ToolQueue 和 MCP 分别什么时候用？

项目默认使用 ToolQueue 异步执行工具。

```text
TOOL_QUEUE_ENABLED=true
  -> ToolQueue 入队，后台异步执行

TOOL_QUEUE_ENABLED=false
  -> MCP Client 直接调用 MCP Server 工具
```

面试回答：

> 默认情况下工具调用走 ToolQueue，因为写 Excel、建个案、发告警不应该阻塞学生端 SSE 回复。ToolQueue 会把工具任务入队，由后台 worker 异步执行，并支持重试、依赖、死信和 Trace。MCP 则提供标准化工具接口，在关闭队列时可以由 MCP Client 直接调用 MCP Server 暴露的工具。

## 15. 普通 CHAT 会不会生成心理报告？

不会。

代码逻辑：

```text
requires_report = intent != CHAT
```

所以：

| 意图 | 生成报告 | 写 Excel |
|---|---|---|
| CHAT | 否 | 否 |
| CONSULT | 是 | 是 |
| RISK | 是 | 是 |

面试回答：

> 普通 CHAT 不生成心理报告，也不会写 Excel。只有 SupervisorAgent 判断为 CONSULT 或 RISK，并且 RiskGuardianAgent 生成了 assessment，Harness 才会创建 `PsychologicalReport`。生成报告后才会触发工具计划。

## 16. 高风险为什么不直接把风险等级告诉学生？

因为心理安全场景下，直接告诉学生“你是高风险”可能造成额外压力或标签化影响。

面试回答：

> 高风险等级、置信度和后台标签只用于系统内部评估和辅导员跟进，不直接展示给学生。学生端更需要的是共情、稳定、安全建议和现实支持引导，比如联系身边可信任的人、辅导员或学校心理中心。这样可以避免标签化和二次压力，也符合心理支持系统的安全边界。

## 总结话术

> 这个项目的核心不是简单调用大模型，而是围绕校园心理支持场景，把多 Agent 路由、RAG 检索、记忆管理、风险评估、工具闭环和 Trace 可观测性串成一个可控系统。普通聊天走轻量 Companion 链路，咨询和风险场景进入 RAG、风险评估和 Counselor 支持链路；风险报告再通过 ToolQueue / MCP 做后台闭环，同时避免学生端感知到内部风险标签。
