# 源码发布说明

上游项目：https://github.com/vnsjvn/CampusMind-Agent

本仓库为二次开发版本，主要新增安全复核、上下文预算管理、结构化分块、检索消融实验与回复 Rubric 评测。
原有实现与本次新增实现应分别描述，不将开源代码表述为全部独立开发。

## 本地启动（PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
New-Item -ItemType Directory -Path data -Force
```

在本地 `.env` 填写 Key 后运行：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```

示例配置采用 SQLite 和无向量 BM25 路径，Redis 不可用时允许数据库回退。
这是演示配置；Chroma 向量路径需要另外确认 embedding API 可用。

## 评测

```powershell
python -m unittest tests.test_rubric_eval tests.test_chunking tests.test_context_builder tests.test_safety_verifier tests.test_runtime_events tests.test_trace_events
python -m app.rubric_eval.runner --mode fixture
python -m app.rag_eval.runner --ablations
```

Rubric 的真实模型评测与人工校准见 `docs/rubric-evaluation.md`。
合成样例预填分数不能当作模型质量指标。生成报告放在被 Git 忽略的 `target/`。

## 发布目录

`scripts/prepare-source-release.ps1` 导出白名单源码并做基础凭据模式扫描，排除环境、数据库、台账、日志和模型权重。
扫描只是一道基础检查，无法证明所有文件都不含敏感内容。该脚本不会删除本地业务数据，也不重写 Git 历史。
`.gitignore` 不会自动取消历史已跟踪文件；本次通过独立源码快照发布到用户仓库，原工作目录保持不变。
