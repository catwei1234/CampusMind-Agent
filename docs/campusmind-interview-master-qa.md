# CampusMind-Agent 面试问题总复习

这份文档用于面试前集中复习，覆盖项目介绍、数据流、Agent、RAG、记忆、数据库、Skill、MCP、评测和二次开发亮点。

## 1. 项目整体

### Q1：这个项目是做什么的？

面向高校学生心理健康支持场景，开发一套多 Agent 智能对话系统，支持学生端流式心理陪伴对话、心理咨询分流、知识库增强回复、风险识别、后台风险报告和高风险告警管理。

### Q2：项目的核心亮点是什么？

可以概括为六点：

- 多 Agent 流程编排：Memory、Supervisor、SafetyVerifier、Knowledge、RiskGuardian、Counselor 等节点职责清晰。
- 意图识别与安全复核：CHAT / CONSULT / RISK 三分类，并用 SafetyVerifierAgent 降低隐晦风险漏判。
- RAG 混合召回：Chroma 向量召回 + BM25 关键词召回 + 分数融合 + 本地 rerank。
- 多轮记忆：Redis 短期记忆 + MySQL 长期摘要记忆。
- 风险闭环：结构化心理报告、风险个案、高风险告警。
- 可观测性：Agent Trace 记录每轮执行路径、RAG evidence、风险评估和回复上下文。

### Q3：整体数据流向是什么？

```text
学生输入
  -> FastAPI /api/chat/stream
  -> 输入脱敏和裁剪
  -> 创建 AgentContext
  -> MemoryAgent 召回记忆
  -> SupervisorAgent 意图识别
  -> SafetyVerifierAgent 安全复核
  -> CHAT: CompanionAgent 生成普通回复
  -> CONSULT / RISK: KnowledgeAgent RAG 检索
  -> RiskGuardianAgent 风险评估
  -> CounselorAgent 生成心理支持回复
  -> SSE 流式返回学生端
  -> 后台保存报告、Trace、工具任务
```

## 2. LangGraph 与 Agent

### Q4：为什么用 LangGraph？

LangGraph 适合有状态、多分支、多 Agent 的流程。这个项目不是一条简单链路，而是需要根据用户意图动态进入不同节点。LangGraph 可以用 State 管理共享上下文，用条件边控制路由，用最大步数防止无限循环，并且方便记录 Trace。

### Q5：LangGraph 相比 LangChain 封装了什么？

LangChain 更像组件库，提供模型、Prompt、Retriever、Tool 等组件；LangGraph 更像流程编排框架，封装了：

- State 状态管理
- Node 节点
- Edge / Conditional Edge 条件路由
- 循环控制
- 多 Agent 编排
- Checkpoint / 恢复能力
- Human-in-the-loop 场景支持

项目里用 `GraphState.context` 挂载自定义 `AgentContext`，再由 controller 根据状态字段决定下一个 Agent。

### Q6：AgentContext 是什么？

AgentContext 是多 Agent 共享状态对象，保存：

- 原始输入和脱敏输入
- 用户和会话信息
- 最近历史和长期记忆摘要
- 意图分类结果
- RAG 检索结果
- 风险评估结果
- 回复消息
- Agent 执行步骤和 Trace 事件

每个 Agent 从 AgentContext 读取自己需要的信息，并把处理结果写回去。

### Q7：项目里的 Agent 是 ReAct 吗？

不是典型 ReAct。项目更像 LangGraph 状态机式多 Agent 编排。每个 Agent 执行固定职责，执行完回到 controller。这样比让模型自由循环更可控，也更适合心理安全场景。

### Q8：controller 怎么选择下一个 Agent？

controller 根据 AgentContext 状态字段判断：

```text
memory_loaded == False -> MemoryAgent
intent_routed == False -> SupervisorAgent
intent_verified == False -> SafetyVerifierAgent
intent == CHAT -> CompanionAgent
knowledge_handled == False -> KnowledgeAgent
risk_assessed == False -> RiskGuardianAgent
response_planned == False -> CounselorAgent
```

## 3. 意图识别

### Q9：SupervisorAgent 怎么做意图识别？

SupervisorAgent 把输入分成三类：

- CHAT：普通聊天、学习、编程、校园事务
- CONSULT：压力、焦虑、低落、失眠、情绪倾诉
- RISK：自杀、自残、伤人或即时危险信号

策略是：

```text
强规则前置
  -> LLM 三分类
  -> 弱关键词兜底
```

强规则用于高确定性分流，LLM 处理模糊表达，弱规则用于模型失败时保守兜底。

### Q10：LLM 分类和本地规则冲突怎么办？

高风险强规则优先级最高，命中就直接 RISK，不交给 LLM 降级。明显任务型表达可直接 CHAT。模糊场景才交给 LLM。LLM 失败后才用弱规则兜底，命中 CONSULT，否则 CHAT。

### Q11：为什么又加 SafetyVerifierAgent？

心理风险表达经常隐晦，比如“以后不用再麻烦大家了”“看不到以后”。SafetyVerifierAgent 会结合当前输入、最近历史和长期摘要，与 RISK / CONSULT 原型句做相似度复核。它只做保守升级，不做降级，降低高风险漏判。

## 4. Memory 记忆机制

### Q12：短期记忆和长期记忆怎么实现？

短期记忆保存当前会话最近聊天记录，优先从 Redis 读取；Redis 没有则从 MySQL 的 `chat_messages` 表兜底，再回填 Redis。

长期记忆保存历史对话压缩摘要，优先从 Redis 读取；没有则查 MySQL 的 `long_term_memories` 表。

流程：

```text
MemoryAgent
  -> Redis 读取最近历史
  -> MySQL 兜底
  -> Redis 读取长期摘要
  -> MySQL 兜底
  -> 脱敏、裁剪、摘要压缩
  -> 写入 AgentContext.memory_brief
```

### Q13：长期摘要怎么生成？

优先调用 LLM 根据历史聊天和当前输入生成摘要；如果 LLM 失败，则使用本地规则摘要兜底。摘要按 `user_id + session_id` 保存到 `long_term_memories`。

### Q14：Redis 在项目里有什么作用？

Redis 用来缓存短期聊天历史和长期摘要，减少每轮都查 MySQL 的开销。MySQL 是持久化兜底，保证 Redis 失效后仍能恢复记忆。

## 5. RAG 召回

### Q15：RAG 发生在什么时候？

RAG 发生在意图识别和安全复核之后、风险评估和心理支持回复之前。只有 CONSULT / RISK 场景触发 RAG，普通 CHAT 不走 RAG。

```text
SupervisorAgent / SafetyVerifierAgent
  -> CONSULT / RISK
  -> KnowledgeAgent
  -> RiskGuardianAgent
  -> CounselorAgent
```

### Q16：RAG 送进去的 query 是什么？

KnowledgeAgent 不直接固定使用原始输入，而是结合：

- 当前用户输入 `model_input`
- MemoryAgent 生成的 `memory_brief`

调用 LLM 做 query rewrite，生成适合检索校园心理知识库的查询词。如果改写失败，则用原始用户输入兜底。

例子：

```text
用户输入：我最近压力很大，晚上总是睡不着
记忆摘要：用户近期多次提到考试压力和作息紊乱
改写 query：考试压力 失眠 作息调节 焦虑缓解
```

### Q17：RAG 怎么召回？

```text
query
  -> Chroma 向量召回最多 16 个候选
  -> BM25 关键词召回最多 16 个候选
  -> 合并去重
  -> vector_score 和 bm25_score 归一化
  -> 0.65 / 0.35 加权融合
  -> 本地 rerank
  -> 取 Top4
  -> 写入 AgentContext.retrieved_knowledge
```

### Q18：为什么选择 Top4？

Top4 是召回效果、上下文长度和噪声控制之间的折中。评测里 Recall@4、MRR、NDCG@4 已经比较稳定；继续增加 TopK 会占用更多 token，也可能引入无关 chunk 干扰心理支持回复。

### Q19：Top4 怎么送给大模型？

KnowledgeAgent 把 Top4 写入 `AgentContext.retrieved_knowledge`。CounselorAgent 调用 `AgentContextBuilder.build_response()`，将召回结果格式化成 evidence block：

```text
[E1] source=sleep-routine-self-care.md, score=0.8765
固定起床时间，减少睡前屏幕刺激……
```

然后作为知识上下文注入系统提示词，并同时写入 Agent Trace。

### Q20：Chroma 是什么？嵌入模型是什么？

Chroma 是向量数据库，负责保存和查询向量。嵌入模型负责把文本转成向量。项目默认使用 `text-embedding-3-small`，输出 1536 维向量。

### Q21：DeepSeek 能不能做 embedding？

DeepSeek 更适合用作 chat model，不一定支持 embedding。项目设计里可以把聊天模型和 embedding 模型拆开：聊天生成用 DeepSeek，向量检索用 OpenAI embedding、BGE 或 Qwen embedding。如果 embedding 不可用，可以降级到 BM25 + 本地 rerank。

### Q22：BM25 是什么？为什么要和向量召回结合？

BM25 是关键词检索算法，考虑词频、逆文档频率和文档长度。向量召回适合语义相似，BM25 适合精确关键词匹配。两者结合可以提高召回稳定性。

### Q23：rerank 是模型吗？

当前项目里的 rerank 是本地规则，不是独立模型。它综合：

- 融合分数
- 词面相似度
- query token 覆盖率
- 短语命中

后续可以接入 bge-reranker 或 Qwen reranker。

### Q24：知识库多大？

当前是轻量校园心理知识库：

- 11 个 Markdown 文档
- 源文件约 31KB
- 切成 34 个知识 chunk
- 入库文本约 1.4 万字符

主题包括焦虑、失眠、学业压力、人际关系、风险策略、咨询转介和隐私边界等。

### Q25：分块太大怎么办？

如果一个文档有结构、每章内容太多，不建议按固定长度硬切。可以改成结构化切分：

```text
先按标题/章节切
章节太长再按段落切
段落仍太长再按 token/字符滑窗切
保留标题路径作为 metadata
```

这样每个 chunk 都能带上章节语义，例如：

```text
source = 心理手册.md
section_path = 第三章/睡眠问题/睡前行为
content = 当前段落内容
```

## 6. 风险评估与安全回复

### Q26：RiskGuardianAgent 做什么？

RiskGuardianAgent 负责结构化心理风险评估。它先用高风险关键词兜底；未命中时调用 LLM 输出 JSON，包括情绪标签、情绪分数、风险等级、置信度和摘要；如果 LLM 失败，则用本地 heuristic 兜底。

### Q27：为什么不把风险等级直接告诉学生？

因为心理健康场景敏感，直接告诉学生“你是高风险”可能造成标签化和二次压力。风险等级用于后台跟进，学生端只输出共情、稳定、安全建议和现实求助引导。

### Q28：CounselorAgent 怎么生成回复？

CounselorAgent 会整合：

- 当前输入
- 最近历史
- 长期记忆摘要
- RAG evidence
- 风险评估结果
- Skill 策略

然后构造 prompt，让模型生成心理支持回复。高风险时强调当前安全、联系可信任的人、辅导员或心理中心，禁止诊断和危险细节。

### Q29：ResponseReviewerAgent 做什么？

ResponseReviewerAgent 在回复生成后做后验安全审查，检查：

- 是否暴露风险等级或报告分数
- 是否有诊断口吻
- 是否承诺绝对保密
- 高风险回复是否缺少求助引导
- 是否出现危险细节
- 是否违反 Skill 的 output_schema

不合格回复会被标记，并可触发人工复核。

## 7. Skill 与 MCP

### Q30：Skill 加载机制是什么？

Skill 放在本地 `skills/` 目录，每个 Skill 一个文件夹，包含 `SKILL.md`，可选 `output_schema.json`。系统通过 `MindBridgeSkillRegistry` 扫描目录，解析 frontmatter、正文提示词、allowed_tools 和输出约束，封装成 `MindBridgeSkill`。

运行时 `MindBridgeSkillLibrary` 根据 intent、risk 和关键词选择 Skill，并注入 prompt。

### Q31：Skill 是提示词吗？

不只是提示词。Skill 更像结构化策略包，包括：

- 适用场景
- 回复原则
- 禁止事项
- 输出约束
- allowed_tools 工具权限

### Q32：MCP 在项目里做什么？

MCP 用来标准化外部工具调用。项目通过 MCP 工具接口完成：

- Excel 台账写入
- 风险个案创建
- 高风险告警发送
- 告警确认
- 个案备注添加

### Q33：MCP 和 Function Call 区别是什么？

Function Call 是模型调用函数的能力，重点是模型选择函数和参数。MCP 更像工具接入协议，重点是把外部工具、资源和服务标准化暴露给 Agent 使用。

### Q34：工具调用会阻塞 SSE 回复吗？

不会。学生端 SSE 回复优先返回，后台工具通过任务队列异步执行，例如写 Excel、创建个案、发送告警，避免阻塞用户体验。

## 8. 数据库设计

### Q35：项目数据库怎么设计？

可以分五类：

1. 用户与会话
   - `user_accounts`
   - `chat_sessions`
   - `chat_messages`

2. 记忆与知识库
   - `long_term_memories`
   - `knowledge_chunks`

3. 心理风险闭环
   - `psychological_reports`
   - `risk_cases`
   - `case_notes`
   - `alert_records`

4. 工具队列与审计
   - `tool_jobs`
   - `dead_letter_records`
   - `tool_audit_records`
   - `excel_records`
   - `operational_alerts`

5. Agent 可观测性
   - `agent_run_traces`

### Q36：各类表怎么用？

`chat_messages` 保存用户和助手消息；`long_term_memories` 保存摘要记忆；`knowledge_chunks` 保存 RAG 切片；`psychological_reports` 保存风险评估报告；`risk_cases` 和 `alert_records` 支撑高风险闭环；`tool_jobs` 支撑异步工具执行；`agent_run_traces` 保存每轮 Agent 执行过程。

## 9. 评测指标

### Q37：意图识别怎么评测？

自建意图识别样例，标注 CHAT / CONSULT / RISK，计算：

- Accuracy：整体分类准确率
- RISK Recall：高风险召回率，重点看漏判
- Macro F1：三类综合效果

### Q38：RAG 怎么评测？

自建 query 和相关 chunk 标注，计算：

- Recall@4：前 4 个是否召回相关片段
- HitRate@4：前 4 个是否至少命中一个相关片段
- MRR：第一个相关片段排得越靠前越高
- NDCG@4：综合衡量排序质量

### Q39：Recall@4、MRR、NDCG@4 分别是什么意思？

Recall@4 看相关片段有没有出现在前 4 个结果中。MRR 看第一个相关片段排第几名。NDCG@4 不只看有没有相关片段，还看相关程度和排序位置。

## 10. 容错与工程稳定性

### Q40：项目有哪些兜底机制？

- Redis 不可用 -> MySQL 兜底
- LLM 意图识别失败 -> 弱规则兜底
- LLM 风险评估失败 -> heuristic 兜底
- query rewrite 失败 -> 原始输入兜底
- embedding 不可用 -> BM25 检索兜底
- 工具执行失败 -> 重试和死信表
- 上下文过长 -> token / 字符预算裁剪
- 高风险回复不合规 -> ResponseReviewerAgent 标记并可人工复核

### Q41：Agent Trace 有什么用？

Trace 记录每轮对话的完整执行链路，包括 Agent 步骤、RAG evidence、风险评估、回复上下文、工具事件和耗时，方便调试、审计和面试展示。

## 11. 项目难点与改进

### Q42：项目最大的难点是什么？

难点主要有三个：

1. 心理风险表达隐晦，单靠关键词容易漏判，单靠 LLM 又不稳定。
2. RAG 检索要兼顾语义和关键词，避免召回噪声。
3. 心理支持回复必须安全可控，不能暴露风险等级、不能诊断、不能提供危险细节。

### Q43：你做了哪些二次开发亮点？

- 新增 SafetyVerifierAgent，对隐晦风险表达做二次复核。
- 增强 ResponseReviewerAgent，对生成回复做后验安全审查。
- 加强 RAG evidence 约束，把召回来源、分数和预览写入 prompt 与 Trace。
- 增加意图识别和 RAG 评测，量化优化效果。
- 增强 token 预算控制，降低长对话上下文冗余。

### Q44：如果继续优化，你会怎么做？

优先做：

- 接入专业 rerank 模型，提升 RAG 排序质量。
- 扩充安全回复评测集，统计高风险回复合规率。
- 将 chat model、embedding model、rerank model 解耦为 Provider。
- 做更完整的 Agent Trace 可视化。
- 增加人工接管流程，让高风险个案更贴近真实业务。

## 12. 一分钟项目总结

> 这个项目是一个面向高校心理支持场景的多 Agent 对话系统。用户消息进入后先做脱敏和记忆召回，再由 SupervisorAgent 和 SafetyVerifierAgent 完成意图识别与安全复核。普通聊天走 CompanionAgent，心理咨询和风险场景进入 KnowledgeAgent 做 Chroma + BM25 混合 RAG 检索，再由 RiskGuardianAgent 生成结构化风险评估，CounselorAgent 结合 Skill 和知识 evidence 生成回复。回复通过 SSE 流式返回，后台通过 Trace 记录 Agent 决策，并根据风险等级触发 MCP 工具完成台账、个案和告警闭环。

