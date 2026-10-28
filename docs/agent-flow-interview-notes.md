# CampusMind-Agent Agent 流程与面试复盘

这份文档用于面试复习，重点解释项目的数据流向、各 Agent 的职责、关键代码位置，以及可能被追问的问题。项目可以理解为一个面向高校学生心理支持场景的多 Agent 系统：前端接收学生输入，后端通过 LangGraph 调度多个 Agent，完成记忆召回、意图识别、知识库检索、风险评估和回复生成，并记录 Trace 与风险闭环数据。

## 1. 整体数据流

```text
学生端输入
  ↓
POST /api/chat/stream
  ↓
FastAPI 路由 chat_stream()
  ↓
ChatService.stream_chat()
  ↓
MindBridgeAgentHarness.run()
  ↓
脱敏 original_input -> model_input
  ↓
create_agent_runtime()
  ↓
LangGraphAgentRuntimeService.run()
  ↓
创建 AgentContext，放入 GraphState.context
  ↓
controller 调度多个 Agent
  ↓
MemoryAgent -> SupervisorAgent
  ↓
CHAT:
  CompanionAgent -> AiClient -> SSE 流式返回
  ↓
CONSULT / RISK:
  KnowledgeAgent -> RiskGuardianAgent -> CounselorAgent -> AiClient -> SSE 流式返回
  ↓
保存聊天记录、心理报告、Agent Trace、风险个案和工具任务
```

关键代码：

| 模块 | 位置 | 作用 |
|---|---|---|
| 前端发送消息 | `app/static/student.js` | 调用 `/api/chat/stream` 并读取 SSE |
| API 路由 | `app/api/routes.py` | 接收聊天请求，返回流式响应 |
| 聊天服务 | `app/services/chat.py` | 调用 Agent 链路，并把 LLM token 通过 SSE 返回 |
| Agent Harness | `app/agents/harness.py` | 脱敏、会话管理、保存消息、报告和 Trace |
| Runtime 工厂 | `app/agents/factory.py` | 根据配置选择 LangGraph runtime |
| LangGraph Runtime | `app/agents/langgraph_runtime.py` | controller 和 StateGraph 编排 |
| Agent 实现 | `app/agents/runtime.py` | Memory、Supervisor、Knowledge、RiskGuardian、Companion、Counselor |

面试回答：

> 用户消息从前端通过 `/api/chat/stream` 进入 FastAPI，后端由 `ChatService` 调用 `MindBridgeAgentHarness`。Harness 会先做输入脱敏和会话管理，再创建 LangGraph Runtime。Runtime 创建 `AgentContext` 作为共享状态，由 controller 根据状态依次调度 Memory、Supervisor、Knowledge、RiskGuardian、Companion 或 Counselor。最后生成的 `response_messages` 交给 `AiClient` 调用模型，并通过 SSE 流式返回前端，同时保存聊天记录、风险报告和 Agent Trace。

## 2. LangGraph Agent Loop

当前项目不是每个 Agent 自己做 ReAct 循环，而是采用中心调度式的 LangGraph loop。

```text
GraphState
  ↓
context: AgentContext
  ↓
controller
  ↓
根据 AgentContext 状态选择下一个 Agent
  ↓
Agent 执行业务并写回 AgentContext
  ↓
回到 controller
  ↓
END 或 max_steps=8
```

关键代码：

| 位置 | 说明 |
|---|---|
| `app/agents/langgraph_runtime.py` | `LangGraphAgentRuntimeService` |
| `app/agents/langgraph_runtime.py` | `GraphState` 只包含 `context: AgentContext` |
| `app/agents/langgraph_runtime.py` | `_build_graph()` 注册 controller 和各 Agent 节点 |
| `app/agents/langgraph_runtime.py` | `_select_next_agent()` 根据状态选择下一个节点 |
| `app/agents/runtime.py` | `max_steps = 8` |

controller 逻辑：

```text
未加载记忆 -> MemoryAgent
未识别意图 -> SupervisorAgent
intent == CHAT -> CompanionAgent -> END
intent == CONSULT / RISK 且未检索 -> KnowledgeAgent
未风险评估 -> RiskGuardianAgent
未构造回复 -> CounselorAgent -> END
达到 max_steps=8 -> END
```

面试回答：

> 我在 LangGraph 上做了一层业务封装，没有把所有字段零散放在 GraphState 里，而是自定义 `AgentContext` 作为统一上下文，再挂到 `GraphState.context`。controller 节点本身不做业务，只根据 `memory_loaded`、`intent_routed`、`knowledge_handled`、`risk_assessed`、`response_planned` 等状态字段决定下一个 Agent。每个 Agent 执行完写回 Context，再回到 controller。这样既利用了 LangGraph 的条件边和状态流转能力，也保证心理安全场景下流程可控，并通过 `max_steps=8` 防止无限循环。

## 3. AgentContext 是什么

`AgentContext` 是一次对话在多 Agent 流程里的共享状态对象。

关键代码：`app/agents/runtime.py`

核心字段：

| 字段 | 含义 |
|---|---|
| `original_input` | 用户原始输入 |
| `model_input` | 脱敏后的输入 |
| `memory_brief` | 记忆摘要 |
| `model_history` | 压缩后的历史上下文 |
| `intent` | 意图分类结果：CHAT / CONSULT / RISK |
| `knowledge_query` | RAG 检索 query |
| `retrieved_knowledge` | RAG 召回结果 |
| `assessment` | 心理风险评估结果 |
| `risk_level` | 风险等级 |
| `response_messages` | 最终交给 LLM 的 messages |
| `steps` | Agent 执行步骤 |
| `events` | Runtime 事件 |
| `context_snapshot` | Trace 展示用快照 |

面试回答：

> `AgentContext` 是多 Agent 之间共享数据的运行时上下文。每个 Agent 不直接强耦合调用另一个 Agent，而是读取和写入 Context。比如 MemoryAgent 写入记忆，SupervisorAgent 写入意图，KnowledgeAgent 写入检索结果，RiskGuardianAgent 写入风险评估，Companion 或 Counselor 写入回复上下文。同时 Context 里的 steps、events 和 snapshot 会用于 Trace 记录，方便后台排查一次对话完整链路。

## 4. MemoryAgent 流程

MemoryAgent 负责会话级记忆召回和摘要压缩。

关键代码：

| 位置 | 说明 |
|---|---|
| `app/agents/runtime.py` | `memory_agent()` |
| `app/services/memory.py` | `LayeredMemoryService.load()` |
| `app/services/memory.py` | `RedisShortTermMemoryStore` |
| `app/services/memory.py` | `MySqlLongTermMemoryStore` |
| `app/services/memory.py` | `compact_history_for_prompt()` |
| `app/services/memory.py` | `summarize_history_for_memory()` |

流程：

```text
MemoryAgent 执行
  ↓
按 session_public_id 从 Redis 读取当前会话最近聊天记录
  ↓ 如果 Redis 没有
按 user_id + session_id 从 MySQL chat_messages 表回查最近消息
  ↓
将 MySQL 查到的消息回填 Redis
  ↓
读取长期摘要
  ↓
优先从 Redis memory-summary 读取
  ↓ 如果 Redis 没有
按 user_id + session_id 从 MySQL long_term_memory 表读取
  ↓
对最近聊天记录做脱敏、裁剪和规则摘要
  ↓
将规则摘要与已有长期摘要合并成 fallback
  ↓
优先让 LLM 根据历史记录和当前输入生成新的 memory_brief
  ↓ 如果 LLM 失败
使用 fallback 摘要
  ↓
新的 memory_brief 写回 MySQL 和 Redis
  ↓
写入 AgentContext.model_history 和 AgentContext.memory_brief
```

会召回什么：

| 内容 | 来源 | 查询方式 |
|---|---|---|
| 最近聊天记录 | Redis，失败回退 MySQL `chat_messages` | Redis 按 `session_public_id`；MySQL 按 `user_id + session_id` |
| 长期摘要 | Redis summary，失败回退 MySQL `long_term_memory` | Redis 按 `session_public_id`；MySQL 按 `user_id + session_id` |

规则摘要：

规则摘要在 `summarize_history_for_memory()` 中生成，本质是一个不依赖 LLM 的确定性 fallback：

```text
遍历历史消息
  ↓
脱敏
  ↓
按 role 区分 user / assistant
  ↓
取最近 4 条用户表达
  ↓
取最近 3 条助手回复
  ↓
每条截断长度
  ↓
拼成“学生近期关注 / 已给过的支持 / 本轮输入关注”
```

面试回答：

> MemoryAgent 采用 Redis 优先、MySQL 兜底的分层记忆读取。它先按 `session_public_id` 从 Redis 读取当前会话最近消息，如果没有命中，就按 `user_id + session_id` 从 MySQL 回查并回填 Redis。长期摘要也是优先 Redis，没有再查 MySQL 的 `long_term_memory`。召回后会对历史消息脱敏、裁剪，并生成规则摘要，与已有长期摘要合并成 fallback。最终优先调用 LLM 根据历史记录和当前输入生成新的 `memory_brief`，失败时用 fallback，并把结果写回 Redis、MySQL 和 `AgentContext`。

## 5. SupervisorAgent 流程

SupervisorAgent 负责意图识别和路由。

关键代码：

| 位置 | 说明 |
|---|---|
| `app/agents/runtime.py` | `supervisor_agent()` |
| `app/agents/runtime.py` | `_classify()` |
| `app/agents/runtime.py` | `GENERAL_TASK_PATTERNS`、`CONSULT_PATTERNS`、`HIGH_RISK_PATTERNS` |
| `app/services/ai.py` | `PromptTemplates.intent_prompt()` |

流程：

```text
读取 AgentContext.model_input 和 model_history
  ↓
强规则优先判断高风险 RISK
  ↓
强规则判断明确任务型 CHAT
  ↓
强规则判断明显心理咨询 CONSULT
  ↓
规则无法确定
  ↓
调用 LLM 做 CHAT / CONSULT / RISK 三分类
  ↓
LLM 调用失败
  ↓
弱规则兜底：有咨询信号判 CONSULT，否则 CHAT
  ↓
写入 AgentContext.intent
  ↓
生成 task_plan
```

当前项目的意图识别可以概括为：

```text
强关键词规则前置
+
LLM 三分类
+
弱关键词规则兜底
```

说明：

| 类型 | 本质 | 作用 |
|---|---|---|
| 强规则 | 高置信关键词 / 模式命中 | 前置拦截 RISK、明确 CHAT 和明显 CONSULT |
| LLM 分类 | 模型根据上下文判断 | 处理规则不确定表达 |
| 弱规则 | 更宽松的咨询信号关键词 | 模型失败时保守兜底 |

评测结果：

```text
70 条自建意图识别样例
Accuracy 94.3%
Macro-F1 94.6%
RISK Recall 100%
```

面试回答：

> SupervisorAgent 是意图路由 Agent，会把输入分成 `CHAT / CONSULT / RISK`。我采用强规则前置、LLM 三分类和弱规则兜底的混合策略。强规则优先拦截明确高风险、任务型请求和明显心理咨询表达；如果规则无法确定，再调用 LLM 返回三类标签；如果 LLM 异常，就用弱咨询规则兜底，命中则判 CONSULT，否则默认 CHAT。分类结果写入 `AgentContext.intent`，controller 再根据 intent 决定后续走 Companion 还是 RAG + 风险评估链路。

## 6. KnowledgeAgent / RAG 流程

KnowledgeAgent 是 RAG 检索节点，只在 `CONSULT / RISK` 场景执行。

关键代码：

| 位置 | 说明 |
|---|---|
| `app/agents/runtime.py` | `knowledge_agent()` |
| `app/agents/runtime.py` | `_rewrite_query()` |
| `app/services/knowledge.py` | `KnowledgeService.retrieve()` |
| `app/services/knowledge.py` | `_retrieve_vector()` |
| `app/services/knowledge.py` | `_retrieve_bm25()` |
| `app/services/knowledge.py` | `_fuse_and_rerank()` |
| `app/services/vector_store.py` | `ChromaKnowledgeStore` |

完整流程：

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
两路结果合并去重
  ↓
向量分数和 BM25 分数归一化
  ↓
按 0.65 / 0.35 加权融合
  ↓
结合关键词覆盖率、短语命中、本地相似度 rerank
  ↓
取 Top4 结果
  ↓
扩展 Top1 相邻 chunk 上下文
  ↓
写入 AgentContext.knowledge_query 和 retrieved_knowledge
  ↓
后续交给 RiskGuardianAgent / CounselorAgent 使用
```

知识库切片：

| 配置 | 默认值 | 含义 |
|---|---:|---|
| `knowledge_chunk_size` | 512 | 每个知识片段长度 |
| `knowledge_chunk_overlap` | 64 | 相邻 chunk 重叠长度 |
| `knowledge_top_k` | 4 | 最终返回给模型的知识数 |
| `knowledge_candidate_k` | 16 | 每路召回的候选数 |

嵌入模型：

默认配置在 `app/core/config.py`：

```text
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

注意：

```text
Embedding 模型负责把文本转成向量
Chroma 负责保存向量和做相似度检索
DeepSeek 主要用于聊天生成，不一定支持 /embeddings
向量不可用时，项目会降级到 BM25 + 本地 rerank
```

召回策略：

| 召回方式 | 作用 | 优点 |
|---|---|---|
| Chroma 向量召回 | 查语义相似 chunk | 用户表达不完全命中关键词时也能召回 |
| BM25 关键词召回 | 查关键词相关 chunk | 对“失眠、焦虑、心理咨询”等明确词更稳定 |
| 分数融合 | 综合两路结果 | 减少单一路召回偏差 |
| 本地 rerank | 根据覆盖率、短语命中等重排 | 提升 Top4 排序质量 |

RAG 评测结果：

```text
60 条自建 RAG 样例
Recall@4 96.7%
HitRate@4 96.7%
MRR 90.8%
NDCG@4 90.5%
```

面试回答：

> KnowledgeAgent 只在咨询和风险场景执行。它先结合 `memory_brief` 和当前输入做 query rewrite，失败时用原输入兜底。检索层通过 `KnowledgeService` 实现，知识文档按 512 字符切片、64 字符重叠存入 MySQL，并在向量能力可用时写入 Chroma。召回时同时走 Chroma 向量检索和 BM25 关键词检索，两路各取最多 16 个候选，合并去重后做归一化和 0.65 / 0.35 加权融合，再结合关键词覆盖率、短语命中等本地规则 rerank，最终返回 Top4，并扩展 Top1 相邻 chunk 保证上下文完整。

## 7. RiskGuardianAgent 流程

RiskGuardianAgent 负责心理风险评估，不直接生成给学生看的回复。

关键代码：

| 位置 | 说明 |
|---|---|
| `app/agents/runtime.py` | `risk_guardian_agent()` |
| `app/services/assessment.py` | `PsychologicalAssessmentService.assess()` |
| `app/services/ai.py` | `PromptTemplates.psychology_prompt()` |

流程：

```text
KnowledgeAgent 完成
  ↓
RiskGuardianAgent 读取当前输入和历史上下文
  ↓
调用 PsychologicalAssessmentService.assess()
  ↓
高风险规则兜底检查
  ↓
调用 LLM 输出严格 JSON
  ↓
解析 emotion / emotionScore / risk / confidence / summary
  ↓
如果 Supervisor 已判 RISK，则风险等级至少提升为 HIGH
  ↓
写入 AgentContext.assessment 和 risk_level
  ↓
后续 CounselorAgent 根据风险等级构造安全回复
```

面试回答：

> RiskGuardianAgent 是风险评估节点，它不会直接给用户输出风险标签，而是调用评估服务生成结构化评估结果，包括情绪、风险等级、置信度和摘要。实现上结合高风险关键词兜底和 LLM JSON 评估，如果 Supervisor 已识别为 RISK，会保证最终风险等级不低于 HIGH。评估结果写入 `AgentContext`，后续 CounselorAgent 根据风险等级调整回复策略，同时后台生成报告和告警记录。

## 8. CompanionAgent 流程

CompanionAgent 负责普通 `CHAT` 场景的回复规划。

关键代码：

| 位置 | 说明 |
|---|---|
| `app/agents/runtime.py` | `companion_agent()` |
| `app/services/context_builder.py` | `AgentContextBuilder.build_response()` |
| `app/services/prompt_builder.py` | `AgentPromptBuilder.build()` |
| `app/services/ai.py` | `PromptTemplates.answer_system_prompt()` |

流程：

```text
SupervisorAgent 判断为 CHAT
  ↓
controller 调度 CompanionAgent
  ↓
设置 risk_level = LOW
  ↓
设置 response_agent = CompanionAgent
  ↓
设置 response_plan = 普通自然回答
  ↓
调用 AgentContextBuilder.build_response()
  ↓
拼接系统提示词、记忆摘要、历史消息、Planner 状态、用户输入
  ↓
不传 RAG 知识 retrieved_knowledge=[]
  ↓
生成 response_messages
  ↓
写入 AgentContext.response_messages
  ↓
ChatService 交给 AiClient 流式生成
```

面试回答：

> CompanionAgent 处理普通聊天、学习、编程和校园事务类请求。它不会直接调用模型，而是根据 `AgentContext` 中的用户输入、历史上下文、记忆摘要和回复策略，调用 `AgentContextBuilder` 构造受上下文预算控制的 prompt，再由 `AgentPromptBuilder` 组装成 `response_messages`。普通 CHAT 不走 RAG 和风险评估，最后由 `AiClient` 根据这些 messages 流式生成回答。

## 9. CounselorAgent 流程

CounselorAgent 负责咨询和风险场景下的心理支持回复规划。

关键代码：

| 位置 | 说明 |
|---|---|
| `app/agents/runtime.py` | `counselor_agent()` |
| `app/services/context_builder.py` | `AgentContextBuilder.build_response()` |
| `app/services/skills.py` | `MindBridgeSkillLibrary.response_skills()` |
| `skills/*/SKILL.md` | 支持性回复、转介、安全计划等 Skill |

流程：

```text
RiskGuardianAgent 完成
  ↓
controller 调度 CounselorAgent
  ↓
读取 intent、risk_level、memory_brief、retrieved_knowledge、knowledge_query
  ↓
根据 intent / risk / 用户输入选择合适 Skill
  ↓
按上下文预算裁剪 skill、knowledge、memory、history
  ↓
构造心理支持回复 prompt
  ↓
高风险时加入安全优先规则
  ↓
写入 AgentContext.response_messages
  ↓
ChatService 调 AiClient 流式生成
```

面试回答：

> CounselorAgent 是心理支持回复规划节点。它会综合 MemoryAgent 的记忆摘要、KnowledgeAgent 的 RAG 结果、RiskGuardianAgent 的风险等级，以及 Skill Library 中的支持性回复策略，构造成最终 prompt。高风险时系统提示词会强调先共情、关注当前安全、建议联系身边可信任的人或学校心理中心，同时禁止输出诊断和危险操作细节。

## 10. 上下文预算控制

项目中不是精确按 tokenizer 计 token，而是用字符数近似控制上下文长度。

关键代码：

| 位置 | 说明 |
|---|---|
| `app/core/config.py` | 上下文预算配置 |
| `app/services/context_builder.py` | 预算裁剪实现 |

默认配置：

```text
context_max_chars = 12000
context_history_max_chars = 4000
context_memory_max_chars = 800
context_knowledge_max_chars = 5000
context_skill_max_chars = 3000
```

流程：

```text
先扣除当前用户输入长度
  ↓
依次给 skill、knowledge、memory、history 分配字符预算
  ↓
超出预算的部分截断
  ↓
历史消息从最近几轮开始保留
  ↓
记录每部分使用量和 truncated_sections
  ↓
写入 context_snapshot，用于 Trace
```

面试回答：

> 我在 `AgentContextBuilder` 中做了上下文预算控制。系统设置总上下文上限，并分别给历史消息、记忆摘要、RAG 知识和 Skill 提示设置子预算。构造 prompt 时按预算截断，历史消息优先保留最近内容，同时记录每个部分的实际占用和截断情况，写入 Trace，方便排查回复质量问题。

## 11. 脱敏机制

关键代码：`app/services/privacy.py`

流程：

```text
用户原始输入 original_input
  ↓
PrivacySanitizer.sanitize()
  ↓
替换手机号、邮箱、身份证号为 [已脱敏]
  ↓
得到 model_input
  ↓
model_input 进入 Agent 和 LLM
```

面试回答：

> 项目在进入 Agent 链路前会先做隐私脱敏，保留原始输入用于业务记录，但传给 LLM 的是 `model_input`。当前规则覆盖手机号、邮箱和身份证号，记忆读写时也会做脱敏。这样可以降低敏感信息进入模型上下文的风险。后续可以扩展学号、微信、QQ、地址和姓名识别。

## 12. SSE 流式输出

关键代码：

| 位置 | 说明 |
|---|---|
| `app/api/routes.py` | `/api/chat/stream` |
| `app/services/chat.py` | `stream_chat()` |
| `app/services/ai.py` | `AiClient.stream()` |
| `app/static/student.js` | 前端读取 SSE |

流程：

```text
Agent 链路先生成 response_messages
  ↓
ChatService 调 AiClient.stream()
  ↓
AiClient 调 DeepSeek / OpenAI-compatible / Ollama / Mock
  ↓
模型 token 分块返回
  ↓
后端包装成 SSE
  ↓
前端逐步渲染
```

面试回答：

> 流式输出是 FastAPI + SSE 实现的。Agent 链路先完成路由、检索、风险评估和 prompt 构造，然后 `ChatService` 调用 `AiClient.stream()` 获取模型流式 token，再以 SSE 格式返回前端。前端 `student.js` 持续读取 chunk 并更新聊天气泡，所以用户能看到逐字生成效果。

## 13. MCP 和工具闭环

项目中 MCP / 工具队列主要用于高风险后处理，而不是阻塞主对话链路。

关键代码：

| 位置 | 说明 |
|---|---|
| `app/services/mcp_client.py` | MCP 工具客户端 |
| `app/mcp_tools/server.py` | MCP 工具服务 |
| `app/services/tool_queue.py` | 工具任务队列 |
| `app/services/tool_registry.py` | 工具注册 |
| `app/services/tool_governance.py` | 工具治理策略 |

典型流程：

```text
RiskGuardianAgent 识别中高风险
  ↓
Harness 生成心理报告
  ↓
ToolQueue 创建风险个案 / Excel 台账 / 告警任务
  ↓
后台 worker 异步执行工具
  ↓
结果写入 risk_cases / alert_records / excel_records
```

面试回答：

> MCP 和工具模块主要做风险闭环，把高风险后的台账、个案和告警从主对话链路中解耦。主链路优先保证学生端流式回复及时返回，风险报告生成后再通过工具队列异步执行 Excel 记录、风险个案创建和告警发送。这样可以避免外部工具调用阻塞对话，也方便做重试、审计和权限控制。

## 14. 常见面试问题与回答

### Q1：你这个项目是 ReAct 吗？

> 不是典型 ReAct。项目没有让每个 Agent 按 Thought-Action-Observation 自主循环，而是采用 LangGraph 状态图编排。每个 Agent 是固定职责节点，通过 `AgentContext` 共享状态，由 controller 决定下一步执行哪个 Agent。这样更适合心理安全场景，因为流程更可控，也方便 Trace 和最大步数限制。

### Q2：为什么用 LangGraph，不直接用 LangChain？

> LangChain 更偏组件封装，比如 Prompt、Retriever、Tool、Chain。LangGraph 更适合有状态流程、条件分支、循环和多 Agent 编排。这个项目需要根据意图和风险状态动态走不同链路，比如 CHAT 直接回复，CONSULT / RISK 进入 RAG 和风险评估，所以用 LangGraph 的 StateGraph 和条件边更清晰。

### Q3：AgentContext 和 GraphState 什么关系？

> GraphState 是 LangGraph 的状态容器，我在里面只放了一个 `context` 字段。`context` 是项目自定义的 `AgentContext`，承载业务状态，比如记忆、意图、检索结果、风险评估和回复 messages。这样业务上下文集中管理，不会散落在多个节点参数里。

### Q4：MemoryAgent 是按什么召回记忆？

> 它不是向量召回，而是按用户和会话维度召回。Redis 按 `session_public_id` 读取当前会话最近消息和 summary；Redis 未命中时，MySQL 按 `user_id + session_id` 回查 `chat_messages` 和 `long_term_memory`。

### Q5：长期摘要是怎么来的？

> 每轮 MemoryAgent 会根据当前会话历史和当前输入生成新的 `memory_brief`。优先调用 LLM 摘要；如果 LLM 失败，则使用规则摘要和已有长期摘要合并后的 fallback。最后按 `user_id + session_id` upsert 到 MySQL 的 `long_term_memory`，同时写入 Redis summary 缓存。

### Q6：意图识别如果规则和 LLM 冲突怎么办？

> 这里设计上是强规则优先。明确高风险、明确任务型请求和明显咨询表达会先由规则确定，减少安全场景漏判。只有规则无法确定时才调用 LLM。LLM 失败后才走弱规则兜底。也就是说不是简单投票，而是按风险优先级和置信度分层决策。

### Q7：强规则和弱规则区别是什么？

> 本质都是关键词或模式匹配。区别在于触发阶段和置信度。强规则放在 LLM 前，用于高确定性分流；弱规则放在 LLM 失败后，用于保守兜底，尤其避免心理咨询场景被误判成普通聊天。

### Q8：RAG 的 16 个候选怎么来的？

> `knowledge_candidate_k=16` 表示每路召回候选数。系统会用 Chroma 向量检索召回最多 16 个语义相似 chunk，同时用 BM25 召回最多 16 个关键词相关 chunk。两路结果合并去重后做分数融合和 rerank，最终返回 Top4。

### Q9：Chroma 是向量数据库还是嵌入模型？

> Chroma 是向量数据库，负责保存 embedding 向量并做相似度查询。嵌入模型负责把文本转成向量，项目默认配置是 `text-embedding-3-small`。

### Q10：DeepSeek 能做 embedding 吗？

> DeepSeek 主要用于对话生成，不一定支持 OpenAI 兼容的 `/embeddings`。项目里把向量检索设计成可降级，如果 embedding 或 Chroma 不可用，就回退到 BM25 + 本地 rerank，保证 RAG 仍然能跑通。生产上可以把聊天模型和 embedding 模型拆开配置。

### Q11：为什么要 BM25 + 向量混合检索？

> 向量检索擅长语义相似，适合用户没有直接说关键词的情况；BM25 擅长精确关键词匹配，比如“失眠”“焦虑”“考试压力”。混合检索可以兼顾语义泛化和关键词精确度，减少单一路召回偏差。

### Q12：为什么 Top1 还要扩展相邻 chunk？

> 知识库是切片存储的，一个 chunk 可能只包含局部上下文。Top1 通常是最相关内容，扩展它的前后相邻 chunk 可以补足上下文，减少回答时断章取义。

### Q13：RiskGuardianAgent 的结果会直接告诉学生吗？

> 不会。风险等级、置信度和后台标签只用于内部评估和后台报告，不直接展示给学生。学生端回复由 CounselorAgent 生成，会强调共情、安全建议和求助资源，避免诊断化表达。

### Q14：怎么保证高风险不漏掉？

> 一方面 SupervisorAgent 前置高风险强规则，明确危机表达直接路由到 RISK；另一方面 RiskGuardianAgent 里也有高风险关键词和 LLM JSON 评估。如果 Supervisor 已判 RISK，即使后续评估偏低，也会把风险等级提升到 HIGH，保证安全优先。

### Q15：Trace 记录了什么？

> Trace 记录每次对话经过的 Agent、每步 action、observation、事件、检索数量、风险等级、上下文预算和截断情况等。这样面试时可以说系统不仅能生成回复，也能解释一次回复是怎么被路由、检索和评估出来的。

### Q16：项目现在有什么可以改进？

> 可以从几个方向改：第一，把聊天模型和 embedding 模型配置拆开，支持 DeepSeek 生成 + BGE/Qwen/OpenAI embedding；第二，增强脱敏规则，覆盖学号、QQ、微信、地址等；第三，完善 RAG 和意图识别评测集，做失败样例分析；第四，增加高风险回复后验校验，检查是否包含危险细节、是否建议线下求助；第五，把 Trace 可视化做得更细，展示每个 Agent 的输入输出和决策原因。

## 15. 简历可用精简表述

项目介绍：

> 面向高校学生心理支持场景，开发多 Agent 智能体系统，支持学生端流式对话、心理咨询路由、知识库增强回复、风险识别、后台报告与高风险告警闭环。

智能路由：

> 基于 SupervisorAgent 实现 CHAT / CONSULT / RISK 三分类，采用强规则前置、LLM 分类与弱规则兜底的混合策略；在 70 条自建样例上达到 Accuracy 94.3%、Macro-F1 94.6%、RISK Recall 100%。

RAG 与记忆：

> 构建校园心理健康知识库，结合 Chroma 向量检索、BM25 召回、分数融合与本地 rerank；在 60 条自建 RAG 样例上达到 Recall@4 96.7%、HitRate@4 96.7%、MRR 90.8%、NDCG@4 90.5%；使用 Redis + MySQL 实现会话记忆和摘要压缩。

风险闭环：

> 结合高风险规则兜底与 LLM JSON 评估生成结构化心理报告，后台支持报告、会话和 Agent Trace 查看，学生端不直接暴露风险分数。

MCP 与工具：

> 基于 MCP 工具与任务队列支持 Excel 台账、风险个案和告警记录，将高风险后处理从对话链路中解耦，避免阻塞学生端流式回复。
