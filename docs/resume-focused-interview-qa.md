# CampusMind-Agent 简历追问版面试题

这份文档只围绕简历中写出的项目亮点整理，适合面试前快速复习。

## 项目概述

### Q1：这个项目一句话怎么介绍？

面向高校学生心理健康支持场景，开发一套多 Agent 智能对话系统，支持学生端流式心理陪伴、咨询意图分流、RAG 知识增强、心理风险识别，以及后台报告、个案和高风险告警闭环。

### Q2：项目核心链路是什么？

```text
用户输入
  -> FastAPI 接口
  -> 输入脱敏
  -> AgentContext
  -> MemoryAgent
  -> SupervisorAgent
  -> SafetyVerifierAgent
  -> CHAT: CompanionAgent
  -> CONSULT / RISK: KnowledgeAgent
  -> RiskGuardianAgent
  -> CounselorAgent
  -> SSE 流式回复
  -> 报告 / Trace / MCP 工具任务
```

### Q3：你的项目重点是什么？

重点不是简单聊天，而是把意图识别、记忆召回、RAG 检索、风险评估、安全回复和后台工具闭环串成一个可控、可解释、可评测的多 Agent 系统。

## 一、意图识别

### Q4：SupervisorAgent 怎么做意图识别？

SupervisorAgent 把输入分成 CHAT、CONSULT、RISK 三类。实现上采用强规则前置、LLM 三分类、弱规则兜底的混合策略。明确高风险先拦截，明显普通任务直接 CHAT，模糊表达交给 LLM，模型失败时用弱咨询规则兜底。

### Q5：为什么要分 CHAT / CONSULT / RISK？

因为不同意图走不同链路：

- CHAT：普通问题，CompanionAgent 直接回复。
- CONSULT：进入 RAG、风险评估、心理支持回复。
- RISK：进入 RAG、风险评估，并可能触发后台个案和告警。

这样可以避免普通问题误触发心理链路，也能保证高风险场景被重点处理。

### Q6：为什么不用纯 LLM 分类？

纯 LLM 成本更高，且高风险场景不能完全依赖模型稳定性。明确的自伤、自杀表达用规则拦截更稳；LLM 主要处理模糊表达，兼顾安全、成本和准确率。

### Q7：为什么不用纯关键词？

纯关键词容易漏判隐晦风险，也容易误判普通任务。比如“以后不用麻烦大家了”可能是风险表达，但不一定命中关键词；“帮我写压力管理作文”包含“压力”，但其实是 CHAT。因此需要规则 + LLM + 复核。

### Q8：SafetyVerifierAgent 是什么？

SafetyVerifierAgent 可以理解成 RiskRecallGuard。它不是简单再调一次 LLM，而是结合当前输入、最近聊天和长期记忆摘要，计算 RISK / CONSULT 原型句相似度、负向趋势分数和强风险信号分数，再用双阈值区分 WATCH / UPGRADE。它只做保守升级，比如 CHAT 到 CONSULT/RISK、CONSULT 到 RISK，不会降级已有风险判断。

### Q9：Accuracy 95%、RISK Recall 97.1% 怎么算？

自建 100 条意图识别样例，人工标注 expectedIntent。系统预测结果与标注一致就算正确，整体正确率是 Accuracy。RISK Recall = 被正确识别为 RISK 的真实高风险样例数 / 所有真实 RISK 样例数。心理场景更关注 RISK Recall，因为漏判代价高。

## 二、RAG 与 Memory 召回

### Q10：RAG 在什么时候触发？

RAG 不会每轮都触发。只有 SupervisorAgent / SafetyVerifierAgent 判断为 CONSULT 或 RISK 时，才由 KnowledgeAgent 执行 RAG。普通 CHAT 不走 RAG，避免增加延迟和无关噪声。

### Q11：RAG 的 query 是什么？

KnowledgeAgent 会结合当前输入和 MemoryAgent 生成的 memory_brief，调用 LLM 做 query rewrite，生成适合校园心理知识库检索的中文查询词。如果改写失败，就用原始输入兜底。

示例：

```text
输入：我最近压力很大，晚上睡不着，快考试了更焦虑
memory_brief：用户近期多次提到考试压力和作息紊乱
query：考试压力 失眠 焦虑缓解 作息调节
```

### Q12：RAG 怎么召回？

```text
query
  -> Chroma 向量召回最多 16 个候选
  -> BM25 关键词召回最多 16 个候选
  -> 合并去重
  -> 两路分数归一化
  -> 0.65 / 0.35 加权融合
  -> 本地 rerank
  -> 返回 Top4 evidence
```

### Q13：Chroma 和 embedding 模型分别是什么？

Chroma 是向量数据库，负责存储和查询向量。embedding 模型负责把文本转成向量。项目默认使用 `text-embedding-3-small`，输出 1536 维向量。

### Q14：为什么向量召回还要 BM25？

向量召回擅长语义相似，BM25 擅长关键词精确匹配。心理知识库里既有口语化表达，也有“失眠、焦虑、咨询转介”等明确关键词，混合召回能提高稳定性。

### Q15：rerank 是模型吗？

当前不是独立 rerank 模型，而是本地规则重排序。它综合融合分数、词面相似度、query token 覆盖率和短语命中。后续如果知识库扩大，可以接入 bge-reranker 或 Qwen reranker。

### Q16：为什么返回 Top4？

Top4 是召回效果、上下文长度和噪声控制的折中。评测中 Recall@4、MRR、NDCG@4 已经稳定；继续增加 K 会占用更多 token，并可能引入弱相关 chunk 干扰回复。

### Q17：Top4 怎么送给大模型？

KnowledgeAgent 把 Top4 写入 `AgentContext.retrieved_knowledge`。CounselorAgent 构造 prompt 时，`AgentContextBuilder` 会把它们格式化成 evidence block：

```text
[E1] source=sleep-routine-self-care.md, score=0.8765
固定起床时间，减少睡前屏幕刺激……
```

然后和用户输入、记忆摘要、Skill 一起送给大模型，同时写入 Agent Trace。

### Q18：RAG 评测指标怎么解释？

- Recall@4：前 4 个结果是否覆盖相关知识。
- MRR：第一个相关结果排得越靠前越高。
- NDCG@4：综合衡量相关结果是否排在前面以及排序质量。

### Q19：RAG 评测集怎么构建？

基于校园心理知识库主题自建 100 条 query，覆盖失眠、焦虑、学业压力、人际关系、新生适应、咨询转介、隐私边界和高风险处理等场景。每条 query 人工标注相关 source 或 chunk，然后调用 `KnowledgeService.retrieve(query, top_k=4)` 计算指标。

### Q20：Memory 怎么实现？

MemoryAgent 先从 Redis 读取当前会话最近聊天记录，Redis 没有则从 MySQL 的 `chat_messages` 兜底并回填 Redis。长期摘要也是先查 Redis，没有再查 MySQL 的 `long_term_memories`。召回后会脱敏、裁剪和摘要压缩，写入 `AgentContext.memory_brief`。

### Q21：为什么用 Redis + MySQL？

Redis 读写快，适合缓存最近聊天和摘要；MySQL 负责持久化，防止 Redis 失效后丢数据。整体是 Redis 优先、MySQL 兜底。

### Q22：摘要压缩怎么做？

MemoryAgent 召回历史后，先做脱敏和裁剪，再优先调用 LLM 生成 1-3 句 memory_brief。如果 LLM 失败，则使用本地规则摘要兜底，避免长对话上下文过长。

## 三、工具调用

### Q23：Skill 是什么？

Skill 不是单纯提示词，而是结构化策略包，包含适用场景、回复原则、禁止事项、输出约束和 allowed_tools 工具权限。CounselorAgent 会根据 intent、risk 和关键词选择 Skill，并注入 prompt。

### Q24：Skill 怎么加载？

Skill 放在本地 `skills/` 目录下，每个 Skill 一个文件夹，包含 `SKILL.md`，可选 `output_schema.json`。系统通过 `MindBridgeSkillRegistry` 扫描目录，解析元信息、提示词内容、allowed_tools 和输出约束，封装成 `MindBridgeSkill`。

### Q25：MCP 是什么？

MCP 是 Model Context Protocol，可以理解为 Agent 和外部工具之间的标准化接入协议。它把外部工具、资源和服务封装成 MCP Server，Agent 通过 MCP Client 按统一格式发现和调用工具。

### Q26：MCP 和 Function Call 区别？

Function Call 更偏模型能力，重点是模型根据 schema 生成函数名和参数。MCP 更偏工具接入协议，重点是把外部工具和资源标准化暴露给 Agent。

### Q27：项目里 MCP 工具有哪些？

- `mindbridge_excel_report`：写入 Excel 台账
- `mindbridge_case_create`：创建风险个案
- `mindbridge_alert_send`：发送高风险告警
- `mindbridge_alert_ack`：确认告警
- `mindbridge_case_note_add`：添加个案备注
- `mindbridge_alert_notify`：通知类工具

### Q28：工具调用流程是什么？

```text
RiskGuardianAgent 生成风险评估
  -> Harness 创建 PsychologicalReport
  -> 根据 risk_level 生成 ToolJob
  -> ToolQueue 异步执行
  -> MCP Client 调用 MCP Server 工具
  -> 写 Excel / 创建个案 / 发送告警
  -> 写入审计和结果表
```

### Q29：为什么和 SSE 流式回复解耦？

写 Excel、创建个案、发送告警是慢操作或外部系统操作。如果同步执行，会阻塞学生端回复。项目里学生端 SSE 优先返回，后台工具任务异步执行，保证对话体验，也支持失败重试和死信处理。

### Q30：怎么防止模型乱调工具？

工具不是模型随便调的。Skill 声明 allowed_tools，ToolGovernance 根据风险等级、工具策略和权限做校验，低风险不能触发高风险告警。工具调用还会写入 `tool_audit_records` 做审计。

## 四、风险闭环

### Q31：风险闭环是什么？

风险闭环指系统不只识别风险，还完成结构化报告、后台查看、个案创建、告警发送和后续跟进记录。

```text
风险识别
  -> 结构化心理报告
  -> 后台报告查看
  -> 中高风险创建个案
  -> 高风险发送告警
  -> 跟进备注
```

### Q32：心理报告怎么生成？

CONSULT / RISK 场景下，RiskGuardianAgent 会生成 assessment，包括 emotion、emotion_score、risk_level、confidence、summary。Harness 根据 assessment 创建 `PsychologicalReport`。

### Q33：RiskGuardianAgent 怎么评估风险？

```text
高风险关键词兜底
  -> LLM 输出严格 JSON
  -> 根据 emotionScore 校准风险等级
  -> LLM 失败时 heuristic 兜底
```

如果 SupervisorAgent 已经判断为 RISK，但 LLM 没给 HIGH，系统会强制提升为 HIGH，避免高风险被低估。

### Q34：LLM JSON 评估返回什么？

返回严格 JSON：

```json
{
  "emotion": "NORMAL|ANXIETY|DEPRESSED|HIGH_RISK",
  "emotionScore": 0.0,
  "risk": "LOW|MEDIUM|HIGH",
  "confidence": 0.0,
  "summary": "short reason"
}
```

这样后端可以稳定解析并写入数据库。

### Q35：普通 CHAT 会生成心理报告吗？

不会。普通 CHAT 不进入风险报告链路，也不会写 Excel。只有 CONSULT 或 RISK，并且 RiskGuardianAgent 生成 assessment 后，才会创建 `PsychologicalReport`。

### Q36：为什么学生端不直接暴露风险分数？

心理健康场景敏感，直接告诉学生风险等级或分数可能造成标签化和二次压力。学生端只输出共情、安全建议和现实求助引导；风险等级用于后台判断和管理员跟进。

### Q37：后台能看到什么？

后台可以查看心理报告、会话记录、Agent Trace、风险个案、告警记录、工具任务和工具审计。Trace 能看到意图识别、SafetyVerifier 是否升级、RAG evidence、风险评估和工具事件。

### Q38：风险等级怎么触发后处理？

- LOW：写入 Excel 台账
- MEDIUM：写台账 + 创建风险个案
- HIGH：写台账 + 创建风险个案 + 发送高风险告警

### Q39：告警发送失败怎么办？

工具任务有重试机制，失败会记录 `last_error` 和 `attempts`。超过最大重试次数后进入 `dead_letter_records`，后台可查看失败原因并人工处理。

### Q40：风险闭环的亮点是什么？

亮点是不止做风险识别，还把风险结果落成结构化报告，并通过 Agent Trace、风险个案和告警工具形成可审计、可跟进的闭环；同时学生端不暴露风险标签，降低二次压力。

## 五、最容易被问穿的点

### Q41：这些指标是不是你真实评出来的？

回答时要稳：

> 是基于我自建评测集跑出来的工程评测结果，主要用于验证当前项目链路优化效果，不是公开 benchmark。评测集覆盖项目目标场景，后续如果生产化，会继续扩展 holdout 数据和人工复核。

### Q42：知识库这么小，RAG 指标高是不是正常？

可以承认：

> 是的，当前知识库是轻量级校园心理知识库，规模不大，所以指标会比较高。这个评测主要验证混合召回链路是否有效。后续知识库扩大后，需要引入更严格的数据划分、hard negative 和 rerank 模型。

### Q43：规则多了会不会过拟合？

回答：

> 会有这个风险，所以规则只处理高确定性场景，比如明确高风险和明显普通任务；模糊表达交给 LLM 和 SafetyVerifier。评测上也会保留边界样例和隐晦表达，后续可扩充 holdout 集做回归。

### Q44：你这个项目最核心的工程能力体现在哪里？

> 核心是把多 Agent、RAG、记忆、风险评估、工具调用和 Trace 可观测性组合成一个完整业务闭环，而不是只做单点 demo。每个模块都有兜底机制和评测指标，能解释、能调试、能持续优化。
