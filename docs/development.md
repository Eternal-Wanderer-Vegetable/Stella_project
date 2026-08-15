# 开发指南

本文覆盖测试、探针脚本、CI 与贡献流程。架构见 [架构说明](architecture.md)，配置见 [配置参考](configuration.md)。

## 环境准备

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

`requirements-dev.txt` 包含 pytest、ruff、numpy 等开发期依赖。numpy 只被 embedding fixture 的向量计算用到，缺失时相关测试会跳过而非报错。

## 提交前检查

```bash
python -m pytest tests -q
ruff check .
```

两条都必须通过。CI 会跑同样的检查（外加 3.10/3.11/3.12 三个版本）。

## 测试

### 运行

```bash
# 全部
python -m pytest tests -q

# 单文件 / 单用例
python -m pytest tests/test_memory_manager.py -v
python -m pytest tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately -v

# 覆盖率
python -m pytest tests --cov=core --cov=memory --cov-branch --cov-report=term -q

# 并行（CI 采用）
python -m pytest tests -n auto --dist loadgroup
```

全部测试使用临时数据库与假 LLM 后端，**不依赖真实机器人、网络或 LM Studio 服务**。

### 测试清单

| 文件 | 覆盖内容 |
|---|---|
| `test_memory_manager.py` | 候选晋升与观察的基础行为 |
| `test_memory_manager_v2.py` | 冲突检测、v2 元字段持久化 |
| `test_memory_manager_fts_sync.py` | FTS 索引与 `memories` 表同步、过期索引自动重建 |
| `test_candidate_reinforcement.py` | 候选强化（累积证据）、Gate 1 三档、超期淘汰、配额竞争 |
| `test_cross_user_isolation.py` | 三条合并路径都不得跨用户（含反向用例） |
| `test_consolidator_core.py` | 整合内部流程、越权候选隔离、JSON 容错解析 |
| `test_consolidation_prompt.py` | 整合 prompt 的防编造条款护栏 |
| `test_source_kind.py` | 来源分级的落库与 prompt 标注 |
| `test_bot_self_source.py` | `BOT_SELF` 标注正确且不进候选白名单 |
| `test_context_tail.py` | 短期上下文：摘要与原始尾巴并存、时间正序 |
| `test_short_term_attribution.py` | 短期记忆的说话人归属 |
| `test_policy.py` | Mode 检测、三层过滤、排序、候选校验 |
| `test_retrieval_v2_and_schema.py` | v2 检索与 Schema 迁移 |
| `test_retriever.py` | 检索排序与回退 |
| `test_rag_switches.py` | RAG 开关组合行为 |
| `test_embeddings.py` | embedding 客户端、语义分注入、失败降级 |
| `test_prompt_builder_v2.py` | 分区注入与 token 预算 |
| `test_pipeline_compose.py` | prompt 拼装顺序（指令型 intent 前置） |
| `test_proactive_rules.py` | 活跃度统计、概率曲线 |
| `test_proactive_state.py` | 配额计数、跨日重置、退避 |
| `test_proactive_target.py` | 目标选择、配额算法、冷却判定 |
| `test_proactive_at_flow.py` | 主动 @ 的记账与退避 |
| `test_proactive_prompt.py` | 主动 @ 指令的护栏 |
| `test_text_similarity.py` | 内容相似度与合并的行为基线 |
| `test_compressor.py` | 去重合并、原子化、归档、节流 |
| `test_timeutil.py` | DB 时间戳按 UTC 解析 |
| `test_trace.py` | 决策追踪与统计 |
| `test_benchmark.py` / `test_benchmark_and_log.py` | Benchmark 运行器与整合日志 |
| `test_db_cleaner.py` | 脏数据清理与消息裁剪 |
| `test_lm_studio.py` | LM Studio 客户端（重试、4xx 放弃、空回复） |
| `test_full_workflow.py` | 端到端：消息入库 → 上下文 → Pipeline → 输出 → 整合 → 晋升 + FTS |

### 写测试的两个约定

**用 `monkeypatch` 而非 `.env`。** 测试不能依赖环境配置：

```python
monkeypatch.setattr("memory.memory_manager.MEMORY_QUOTA_ENFORCE", True)
monkeypatch.setattr("memory.memory_manager.DB_PATH", tmp_path / "test.db")
```

**约束型测试必须配反向用例。** 只测「不该发生的没发生」是不够的——把条件写成永假也能通过，功能会静默失效。`test_cross_user_isolation.py` 的每条「不得跨用户合并」都配了一条「同用户仍要合并」。

## 探针脚本

模型侧的验证不走 pytest（需要真实本地模型），用 `scripts/` 下的探针。**它们跑生产链路**：同一份 prompt 模板、同一份解析逻辑、同一份候选校验。

### 整合探针

```bash
# 正例回归基准：验证「该记的时候记得住」
python scripts/probe_consolidation.py --positive --repeat 3

# 真实窗口观察
python scripts/probe_consolidation.py --limit 20

# 只打印 prompt，不调模型（离线比对格式化是否被改动）
python scripts/probe_consolidation.py --positive --print-prompt

# 单窗口稳定性观察
python scripts/probe_consolidation.py --window-index 3 --repeat 3

# 覆盖采样温度
python scripts/probe_consolidation.py --positive --repeat 3 --temperature 0.0
```

**改动 `memory/consolidation_prompt.py` 后必须跑双向闸门**：

```bash
python scripts/probe_consolidation.py --positive --repeat 3   # 正例必须全绿
python scripts/probe_consolidation.py --limit 20              # 编造率必须 ≈ 0
```

两条都过才算成功。只看一边会漏掉另一边的退化——放宽捕获时正例会变好但可能开始编造，收紧时编造率归零但会漏掉合法事实。

### 采样真实窗口

```bash
python scripts/sample_windows.py     # 产出 windows_raw.json（含真实数据，已 gitignore）
```

**注意采样偏差**：脚本按 `signal_score`（长句数 − 图片数）降序排列后取「前 12 高信号 + 中间 8 中等 + 末 10 刷屏」。因此 `--limit 20` 实际只跑到高信号与中等层，**其产出率不可外推到生产**。用 `--stratum` 指定分层可使口径显式化。

曾有一次误判源于此：探针 20 窗口产出 3 条候选（10%），而生产 985 条消息产出 0 条，一度被当成缺陷；实际是两者输入分布不同。

### Benchmark

检索层的评估数据集在 `memory/benchmark/`：

```bash
python -m memory.benchmark                        # rule-only
python -m memory.benchmark --verbose              # 每用例明细 + 分数分解
python -m memory.benchmark --embedding-fixture memory/benchmark/_fixtures/embeddings_xxx.json
python -m memory.benchmark --compare              # rule-only vs embedding 对照
```

核心指标：Memory Precision、Recall、Forbidden Activation（目标 ≈ 0）、Pollution Rate、Mode 检测准确率、Behavior Guard Hit。

用例格式见现有 JSON。`_fixtures/` 存放向量数据与整合正例基准，不被当作检索用例加载。

```bash
python scripts/build_embedding_fixture.py    # 构建向量 fixture（需 embedding 服务）
python scripts/probe_embedding.py            # 探测 embedding 服务可用性
```

## 数据库

```bash
python -m memory.schema --dry-run    # 预览待执行的迁移
python -m memory.schema              # 执行迁移
python -m memory.schema --backup     # 仅备份
```

**迁移原则：Additive Migration** —— 只加字段与索引，绝不删数据。所有 `ALTER` 都经过 `PRAGMA table_info` 探测，幂等可重跑。首次迁移前自动备份为 `stella_memory_backup.db`。

### 加字段的正确做法

1. `memory/schema.py` 的 `SCHEMA_VERSION` +1
2. `_ADDITIVE_COLUMNS` 追加 `(表名, 列名, ALTER 语句)`
3. `_INDEXES` 追加需要的索引
4. **同步更新所有手写该表的 `CREATE TABLE`**

第 4 步是历史踩坑点：`memories` 表的建表语句曾在 `schema.py` / `consolidator.py` / `memory_manager.py` / `compressor.py` 四处各有一份，加 `source_kind` 时漏了 compressor 那份。现在统一走 `schema.create_memories_table(conn)`，新增表也应照此办理。

SQLite 的 `ALTER TABLE ADD COLUMN` **不接受非常量默认值**，`DEFAULT CURRENT_TIMESTAMP` 会失败，需留空由代码写入。

### 时间处理

`CURRENT_TIMESTAMP` 写入 **UTC**。所有「拿 Python 时间与 DB 时间戳比较」的地方必须走 `memory/timeutil.py`：

```python
from memory.timeutil import parse_db_timestamp, seconds_since, db_timestamp_str
```

直接用 `datetime.now()` 与 DB 时间戳比较会在非 UTC 时区产生固定偏移。这个 bug 曾让 `PROACTIVE_AT_USER_COOLDOWN` 在 UTC+8 下完全失效（永远被判为已过冷却），且只在 CI 的 UTC 环境下才暴露。

SQL 内部的比较（`julianday('now')` vs `julianday(col)`）两侧同为 UTC，无需处理。

### 归档记录

每次大重构后运行时数据库会归档到 `_deprecated/`（已 gitignore）：

| 文件 | 说明 |
|---|---|
| `legacy_agent_memory.db` | 早期版运行库 |
| `legacy_agent_memory_2026.db` | v2 schema 升级前 |
| `legacy_agent_memory_pre_v4.db` | 两层过滤重构（Gate 1 三档 / 候选强化 / 配额）之前 |

启动时会按当前 schema 在 `memory/` 下自动重建新库。

> 封存旧库时**连 `stella_memory_backup.db` 一起移走**。`backup_database()` 见备份已存在即跳过，留着它会导致新库将来迁移时不生成新备份——一个看起来有备份、实际备份错了的状态。

## CI

`.github/workflows/ci.yml`，四个 job：

| Job | 内容 |
|---|---|
| `lint` | `ruff check .`（Python 3.11） |
| `security` | `pip-audit -r requirements.txt`（阻塞）+ `bandit`（非阻塞，报告上传为 artifact） |
| `test` | 3.10 / 3.11 / 3.12 三版本矩阵，`pytest tests/ --cov=. --cov-branch -n auto`，覆盖率报告上传为 artifact |
| `notify` | 仅 PR：汇总状态并评论 |

`test` 依赖 `lint` 与 `security` 通过；`fail-fast: false` 保证某个版本失败时其余继续。同一分支的旧工作流会被自动取消。

**本地复现 CI 环境**：

```bash
pip install -r requirements.txt -r requirements-dev.txt pytest pytest-cov pytest-xdist
ruff check .
pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup
```

`pip-audit` 是阻塞的，某个上游依赖爆出 CVE 时 CI 会红。若判断为不可立即修复的上游问题，可临时在该步骤加 `|| true`，但应记录原因。

## 代码约定

**Lint / 格式**：ruff（配置在 `pyproject.toml`）。未使用 black —— 不要引入 black 格式化，会造成大面积无意义 diff。

**类型检查**：pyright（`pyrightconfig.json`）。CI 不跑类型检查，但新代码应带类型标注。

**注释写「为什么」而不是「做什么」**。项目里大量注释记录了某个阈值的实测依据、某个顺序的必要性、某个 bug 的成因——这类信息删掉之后无法从代码反推。例如：

```python
# confidence / importance 权重刻意压到 0.05：它们描述「记忆本身可靠/重要」，
# 与「当前该不该用这条」关系弱，只适合做 tie-breaker。否则 conf≈0.98 的
# 高质量诱饵会在「该不该用」上作弊。
```

**逻辑不要有第二份副本**。`memory/text_similarity.py` 的存在就是因为相似度判定曾在三个模块各有一份，跨用户合并 bug 需要修三次而漏了两次。

**Prompt 改动需要护栏**。`tests/test_consolidation_prompt.py`、`tests/test_proactive_prompt.py` 对关键条款做字符串断言，包括反向断言（确认已移除的条款没被写回来）。这类条款删掉后功能仍「正常工作」但效果立刻变差，只能靠断言锁住。

## 排查问题

| 现象 | 查看 |
|---|---|
| 回复内容不对 | `stella_thought_logs.md`（完整 prompt / 原始输出 / 内部思考） |
| 记忆没生成 | `memory_consolidation_log.md`（每批整合的原始输出与候选数） |
| 记忆被误删 | `memory_compressor_log.md` + `compressor_stats` 表 |
| 检索选错记忆 | `memory_traces` 表（候选 / 过滤 / 最终 / 拒绝），或 `python -m memory.benchmark --verbose` |
| 主动发言异常 | 日志里的 `🎯 [主动@]` / `🔇 未回应`；`proactive_state` 表 |
| NapCat 掉线 | `napcat_launch.log`、`NapCat.Shell/logs/`、日志里的 `[Watchdog]` |
| 整合输出被截断 | 日志里的 `finish_reason=length` 告警 |

### 常用 SQL

```sql
-- 候选队列状态分布
SELECT status, COUNT(*), AVG(confidence), AVG(occurrence_count)
FROM memory_candidates GROUP BY status;

-- 卡在观察区的候选（被反复提及却晋升不了的）
SELECT user_id, content, confidence, occurrence_count, source_kinds, first_seen_at
FROM memory_candidates WHERE status = 'OBSERVING' ORDER BY occurrence_count DESC;

-- 每用户记忆数（配额观察）
SELECT group_id, user_id, COUNT(*) FROM memories
WHERE status = 'active' GROUP BY group_id, user_id ORDER BY 3 DESC;

-- 记忆的来源分布（审计：哪条路径产生的）
SELECT source_kind, COUNT(*) FROM memories WHERE status = 'active' GROUP BY source_kind;

-- 消息来源分布
SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind;

-- 整合进度
SELECT * FROM consolidation_state;

-- Schema 版本
SELECT * FROM schema_meta;
```

## 提交与贡献

**提交信息**用简短的英文或中文描述改动实质，避免「fix bug」「update」这类无信息量的描述。

**PR 前确认**：

- `python -m pytest tests -q` 全绿
- `ruff check .` 无警告
- 改了 prompt → 跑过双向闸门（正例回归 + 真实窗口）
- 改了 schema → `python -m memory.schema --dry-run` 输出符合预期
- 改了配置项 → `.env.example` 同步，`docs/configuration.md` 同步

**改动涉及以下内容时请在 PR 描述里说明理由**：

- 记忆晋升的阈值或判定逻辑
- prompt 中的防编造条款
- 三条合并路径的归属过滤
- 看门狗的重启判据

这些地方都有过实测依据（记录在 `design_docs/check_point/` 与 `bug_report/`），改动前建议先读相关记录。

## 设计记录

`design_docs/` 是设计过程的存档，面向开发者自己：

| 目录/文件 | 内容 |
|---|---|
| `Memory *Specification v1.0.md` | 记忆系统的原始规范（Schema / Consolidation / Retrieval / Policy Matrix / Evaluation & Debug） |
| `Migration & Implementation Plan.md` | v1 → v2 的迁移计划 |
| `Memory Verification Loop.md` | 主动获取回路的设计 |
| `check_point/` | 关键决策节点：问题、诊断过程、被否证的假设、实测数据 |
| `bug_report/` | 缺陷分析 |
| `logs/` | 终端输出与运行日志存档 |

与 `docs/` 的区别：`docs/` 是面向使用者的成品文档，`design_docs/` 是过程记录，包含被推翻的假设与失败的尝试——那些信息对理解「为什么现在是这样」很重要，但不适合放进使用文档。