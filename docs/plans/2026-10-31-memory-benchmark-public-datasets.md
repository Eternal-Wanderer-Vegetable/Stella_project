# 计划：Stella 记忆系统公开数据集 Benchmark 评测（MBENCH-002）

- 日期：2026-10-31
- 分支：`codex/memory-benchmark`（基于 cf63061）
- 状态：已批准，执行中
- 来源：ChatGPT 分享对话「研究Hy记忆」（share 6ad2301c）中的评测讨论结论

## 背景与定位

该讨论在 Hy-Memory 研究后提出 SMB（Stella Memory Benchmark）分层评测构想，并明确：公开数据集作为**独立外部对照测试**，须固定数据版本、评测协议、判分模型；最优先缺口是「从原始对话到最终回答的隔离回放」。

现状核对：

- `memory/benchmark.py`（检索层）：预写记忆→测检索；PersonaMem-v2 已适配并在 CI 跑 200 例子集（MBENCH-001 done，gate 98%），全量 5000 行离线跑在 progress.md:888 明确延后。
- `scripts/eval_memory_replay.py`（写路径回放）：真实走 整合→EXTRACT→候选→证据合同→晋升，但语料为合成日常套件，QA 判定是子串匹配，无 LLM judge、无公开数据集。
- **本轮补缺口**：公开长对话数据集 × 真实摄入 × 真实混合检索 × LLM judge 的端到端评测。

## 数据集选择

| 数据集 | 本轮 | 说明 |
| --- | --- | --- |
| LoCoMo（snap-research，10 段多会话长对话，约 1986 QA 五类） | M1 主做 | 记忆系统标准基准（Mem0/Zep 均用），自带证据标注可算检索命中率 |
| PersonaMem-v2 全量 5000 行（检索层四模式 matrix） | M3 顺带 | 已有 fetch/adapt 全套，零 LLM 成本，补延后项 |
| LongMemEval / LongMemEval-V2 | 不做 | 语料 6–12 万 token/题成本高，列入报告 Next |

语言：LoCoMo **英文原样**（证据合同已内置英文窄句型 `_SELF_REPORT_PATTERNS`/`_PREFERENCE_PATTERN_EN`，`memory/evidence_contract.py`；与公开数字可比；中文翻译版列为备选）。

## 交付物（全部纯增量，不改生产代码）

1. `scripts/fetch_locomo.py`（复刻 `fetch_personamem.py`：固定 revision + sha256 + httpx，数据入 `memory/benchmark/_public/locomo/`，该目录已被 `.gitignore:128` 整体忽略）+ `scripts/adapt_locomo.py`（sessions + QA + category + evidence turn）。
2. `memory_eval/` 包：
   - `ingest.py`：隔离 STELLA_HOME/临时 DB（直接插 `group_messages` 回填时间戳 + patch 各模块 `DB_PATH`，模式取自 `scripts/eval_memory_replay.py:109,149`）；`capture=None` 绕过 capture gate（回放脚本既有约定，报告注明）；每会话 `consolidate_group(force=True)` 走真实 EXTRACT→候选→证据合同→晋升。
   - `answer.py`：`retrieve_memories(_emb)` + `build_v2_named_sections` + `RealEndpointModel`（温度 0）短答。
   - `judge.py`：LoCoMo 标准协议 LLM-as-judge，prompt 固定版本入库；adversarial 类按弃答判定。
   - `metrics.py`：分类 J-accuracy、adversarial 弃答率、检索 evidence hit@K、捕获漏斗四级计数（候选/accepted/晋升/可检索）、成本（调用数/token/P50 延迟）。
   - `report.py` + `__main__.py`：CLI `--conversations N --qa-sample N --mode rule|fts|hybrid --out`，checkpoint/续跑。
3. `tests/test_memory_eval_*.py`：假模型零网络；v2 用例显式开回 `MEMORY_V2_ENABLED`；不建 `tests/<pkg>/__init__.py`（遮蔽陷阱）。
4. `docs/reports/2026-10-31-locomo-memory-benchmark.md` + `.en.md` + evidence manifest（commit SHA/schema 版本/模型 ID/数据集 sha256/种子）。
5. `feature_list.json` 新增 MBENCH-002（先 `planned`，结束翻 `done`，避开「同时仅一个 in_progress」门禁）+ progress.md + session-handoff.md 登记。

## 模型端点（2026-10-30 现状）

Strata 8081 未启动；LM Studio 127.0.0.1:1234 在线（六个模型：qwen/qwen3.8-27b、google/gemma-4 系、text-embedding-qwen3-embedding-0.6b、nomic-embed）。运行前探测选定 answer/judge/extraction 模型并记录；embedding 缺失则降级 rule/fts 并记录。端点缺失的维度标 NOT READY。

## 执行顺序

1. 存档本计划 → 2. 前置核对（feature_list 现状、GitNexus impact、端点探测）→ 3. fetch+adapt LoCoMo smoke → 4. `memory_eval` 实现+单测+ruff → 5. 真实端点 smoke（2 会话×抽样 QA）→ 6. LoCoMo 全量（checkpoint 续跑，后台任务）→ 7. PersonaMem 全量 matrix → 8. 报告+登记 → 9. 门禁（ruff/check_docs/pytest/detect-changes --scope all）+ 提交。

## 提交策略

工作区含出站会话未提交改动（corona/、deployment docs、feature_list.json、progress.md、session-handoff.md、未跟踪 ligamina_bridge/start_managed_stella.ps1）——不得混入。新增文件单独提交；三个共享文件用 `git diff(A_outbound→A_mixed)` 提取仅含本轮新增 hunk 后 `git apply --cached` 外科式暂存（失败则回退 stash→干净基上重做编辑→提交→pop→还原）。

## 验收标准

- LoCoMo 运行完成并出报告，每个数字绑定命令+环境指纹；端点缺失维度标 NOT READY。
- `memory_eval` 单测全绿；`ruff check .` / `check_docs.py` / pytest / `detect-changes --scope all` 四门禁通过；数据不入库；不加入 release COMMON_DIRS。

## 已知局限（写入报告）

- 证据合同仅接受窄句型（居住/来自/称呼/雇主/一般偏好），非句型事实当前版本不可晋升——这是真实现状，漏斗分解负责归因。
- LoCoMo gold 约 6% 已知噪声（Penfield Labs 独立审计，2026）。
- judge 与被测同源模型的自评偏差。

## 执行记录（2026-10-31 当日回填）

- 计划已执行完毕，报告见 `docs/reports/2026-10-31-locomo-memory-benchmark.md`。执行中的设计与计划差异：
  1. **live 端到端全量 QA 未跑**（标记 NOT READY）：live 漏斗证明写侧（证据合同句型覆盖 0.29%）使端到端成绩趋近下限，信息量低于 oracle+gold 上界配置；以「live 漏斗（1 段）+ oracle+gold 上界（10 段）」组合交付。
  2. 新增**分解实验**（计划外的增量价值）：`--pack-mode conflict` 与 `MEMORY_SCORE_MIN=0.15` 均不改变证据入包率，实证检索排序（recency+ctx 权重）是主约束。
  3. 模型路径变化：LM Studio 1234 显存耗尽无法加载聊天模型（e2b 仅能半卸载、整合一批 5 分钟不可用），按用户指示切换 **Strata 8081（qwen3.8-flash-next-iq2_xs）** 作 answer/judge/整合；embedding 仍用 1234 的 qwen3-embedding-0.6b。
  4. 两个回放工件当场修复并记录：候选 first_seen_at 保持墙钟（TTL 工件）、gold 按证据会话回填（freshness 池工件）。
