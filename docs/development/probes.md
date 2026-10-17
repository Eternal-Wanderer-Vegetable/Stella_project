# 探针脚本

中文 | [English](probes.en.md) · [文档总览](../README.md)

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

# 两阶段链路（生产行为）：阶段1 出 has_self_disclosure，阶段2 提取候选
python scripts/probe_consolidation.py --positive --two-stage

# 单阶段对照（旧行为，用于确认两阶段的增益）
python scripts/probe_consolidation.py --positive
```

**改动 `memory/consolidation_prompt.py` 后必须跑双向闸门**：

```bash
python scripts/probe_consolidation.py --positive --repeat 3   # 正例必须全绿
python scripts/probe_consolidation.py --limit 20              # 编造率必须 ≈ 0
```

两条都过才算成功。只看一边会漏掉另一边的退化——放宽捕获时正例会变好但可能开始编造，收紧时编造率归零但会漏掉合法事实。

> **两阶段的区分性测试**。`insomnia_breakfast_noisy` 用例把同样的自我披露信息埋在 Bot 寒暄、彼岸花刷屏与单字附和之中，复现生产的失败条件：
>
> | 路径 | 结果 |
> |---|---|
> | 单阶段（整合模型） | ❌ 1/2（漏掉「失眠」） |
> | 两阶段（整合模型 → 主聊天模型） | ✅ 2/2 |
>
> 其余 4 个干净用例两条路径都通过——**只有噪音用例有区分度**。改动 `extraction_prompt.py` 或调整阶段 2 模型后，这个用例必须保持 2/2，否则两阶段就白做了。
>
> 输出里的这两行是失败归因的关键：
>
> ```
> 阶段1 has_self_disclosure=True/False，阶段2 已调用/未调用
> ↳ 该信息出现在原始输出中但未进候选（模型主动弃掉，非未察觉）
> ```
>
> 第一行区分「小模型布尔判错」（阶段 2 根本没被唤醒 → 改 `consolidation_prompt.py`）与「大模型提取失败」（唤醒了但没提出来 → 改 `extraction_prompt.py`）；第二行区分「没看到」与「看到了但主动弃掉」，两者修法完全不同。

### 插件 LLM 探针

`astrbot_compat` 的 LLM 接入面（插件调模型、函数工具、多轮会话）在 pytest 里
`chat_completion` 是打桩的，**「能不能真的问到模型」「小模型会不会真的调工具」只有这个探针能答**：

```bash
python scripts/probe_astrbot_llm.py                     # 全部小节
python scripts/probe_astrbot_llm.py chat tools          # 只跑指定小节
```

| 小节 | 验证什么 |
|---|---|
| `chat` | `provider.text_chat()` 能拿到非空回复，并打印 usage |
| `persona` | 人格三态：插件给了用插件的、没给注入插件专属人格、配置为空串则不发 system |
| `stream` | `text_chat_stream()` 中途是分片、最后一次 yield 是完整文本 |
| `tools` | `run_tool_loop()` 是否真的触发函数调用并把结果复述给用户 |
| `budget` | 超预算的上下文被成对裁掉最早的几条，而不是被服务端拒 |
| `conversation` | `ConversationManager` 落库往返（不需要模型） |

它跑的是生产链路：`core/llm/scheduler` 里 PLUGIN 角色所属端点槽的闸门（纯本地默认 `LOCAL`）→ `core/llm/openai_client.py` →
`StellaChatProvider` → `run_tool_loop`。会话与偏好读写指向临时库，**不会碰 `DB_PATH`
对应的真实数据库**。

`tools` 小节失败时要先分清是链路问题还是模型能力问题：日志里出现
`请求估算 N token（消息 x 条，工具 1 个）` 说明工具已随请求送出，此时模型仍不调用
就是本地小模型 function calling 能力不足，换更大的模型再试。

### 采样真实窗口

```bash
python scripts/sample_windows.py     # 产出 windows_raw.json（含真实数据，已 gitignore）
```

**注意采样偏差**：脚本按 `signal_score`（长句数 − 图片数）降序排列后取「前 12 高信号 + 中间 8 中等 + 末 10 刷屏」。因此 `--limit 20` 实际只跑到高信号与中等层，**其产出率不可外推到生产**。用 `--stratum` 指定分层可使口径显式化。

曾有一次误判源于此：探针 20 窗口产出 3 条候选（10%），而生产 985 条消息产出 0 条，一度被当成缺陷；实际是两者输入分布不同。

### Benchmark

检索层的评估数据集在 `memory/benchmark/`（手写用例按类别分目录；`generated/` 为
`scripts/generate_benchmark_cases.py` 的确定性产物，同 seed 字节级一致）：

```bash
python -m memory.benchmark                        # rule 模式
python -m memory.benchmark --verbose              # 每用例明细 + 分数分解
python -m memory.benchmark --retrieval-mode fts   # 检索模式矩阵：rule/embedding/fts/hybrid
python -m memory.benchmark --matrix               # 四模式全矩阵（embedding 需 fixture）
python -m memory.benchmark --embedding-fixture memory/benchmark/_fixtures/embeddings_xxx.json
python -m memory.benchmark --compare              # rule-only vs embedding 对照
python -m memory.benchmark --gate                 # 质量门禁：用例失败或硬零违规非零退出
```

核心指标：Memory Precision、Recall、Forbidden Activation（硬零门禁）、Pollution Rate、
Mode 检测准确率、Behavior Guard Hit；维度族 `dimensions`：temporal_accuracy、
supersede_accuracy、abstain_correct_rate、**cross_scope_leak_rate（硬零门禁）**、
lineage_completeness；成本段 `cost`（延迟分位数/库尺寸，机器相关只观测不门禁）。

报告契约与基线（CI 质量门禁的依据）：

```bash
python -m memory.benchmark --report docs/reports/evidence/<dir>   # 报告 + manifest
python -m memory.benchmark --compare-baseline memory/benchmark/_fixtures/baselines/2026-10-16.json
```

- 冻结基线 `memory/benchmark/_fixtures/baselines/`：逐指标零容差对比（硬零指标
  强制零容差，新指标记 new 不算漂移）。数据集或打分有意变更后必须重生成基线并过审；
- `tests/test_benchmark.py::test_baseline_gate_per_metric_zero_tolerance` 是 CI 门禁。

用例格式 v2（全可选）：`last_accessed_at_offset_minutes` / `last_confirmed_at_offset_minutes`
（相对时钟锚点）、memory `status`（superseded/archived）、`evidence`（血缘声明）；
case 级 `expect_empty`（abstain）、`expect_evidence`（血缘断言）、`topic`（分题型聚合）。
`_` 前缀路径段（`_fixtures/`、`_public/`、`_replay/`、`_baselines/`）不作为用例加载。

```bash
python scripts/build_embedding_fixture.py    # 构建向量 fixture（需 embedding 服务）
python scripts/probe_embedding.py            # 探测 embedding 服务可用性
python scripts/generate_benchmark_cases.py --check   # 生成产物冻结校验
```

> **检索模式矩阵的两个实证发现**（2026-10-16，`memory/retrieval_v2.py` 零改动测得）：
> ① FTS 候选路径对自然中文查询恒 0 命中——`_segment_text` 把整条查询串与滑窗片段
> 全部作为 MATCH token，FTS5 隐式 AND 语义要求文档包含全部 token，实际检索总是
> 回退新鲜度路径（`retrieval_path.candidate_rows` 可复核）；
> ② embedding/hybrid 模式只评 fixture 覆盖的用例（按查询向量在场判定），
> 未覆盖用例显式 skip 记账——用「embedding 权重 + 规则语义回退」跑会产出第三种
> 语义，指标失真。fixture 已于 2026-10-17 重建（259 向量覆盖 101/101 用例），
> 重建需 embedding 服务（`python scripts/build_embedding_fixture.py`，注意本机
> 系统代理会劫持 127.0.0.1，须 `NO_PROXY=127.0.0.1,localhost`）。
> ③ 用例偏移字段必须写 `last_confirmed_at_offset_minutes`（排序读 confirmed 列）——
> 只写 `last_accessed_at_offset_minutes` 时 recency 判别不生效，rule 模式靠 conf/imp
> 差侥幸通过、真实 embedding 下新旧事实的 sem 差会抵掉 conf/imp 差导致旧值激活
> （2026-10-17 第一次真模型验收实测，7 例踩硬零后修复）。

### Rust parity 与写路径回放

```bash
python -m memory_rust.benchmark --compare          # Python vs native 逐例对照
python -m memory_rust.benchmark --matrix           # 四模式矩阵（fts/hybrid 仅 Python 单边）
python scripts/eval_memory_replay.py               # 写路径回放（recorded，CI 可跑）
python scripts/eval_memory_replay.py --live --record recorded/new.json   # 离线真实模型 + 录制
```

- parity 基线 **101/101 hard matches**（2026-10-16 起，21/24 旧数字作废）：
  闭环靠两步——harness 保真修复（`semantic_scores=None` 不再折叠成 `{}`，此前
  双实现跑的是不同打分语义）+ Python 侧补齐与 native 一致的 canonical tie-break
  （score desc → memory id asc）。`tests/test_memory_rust_benchmark.py::test_parity_gate_full_dataset`
  是门禁：native 可加载时硬差异必须为 0，不允许 allowed_diffs；native 缺席显式 skip。
- 写路径回放走生产链路（消息批次 → 录制件驱动生成 → 证据评估 → 候选 → 晋升 →
  检索 QA），指标：extraction_hit_rate、fabrication_rate（4-gram 原文交集规则）、
  promotion_correctness、qa_accuracy、memory_delta（有/无记忆差）。门禁要求全绿
  且 memory_delta > 0。套件在 `memory/benchmark/_replay/daily-life/`。
  `--live` 走真实装配（阶段2 按当前配置解析）；live 录制件存
  `recorded/live-20261017.json`。**2026-10-17 真模型验收发现**：生产配置
  `LLM_ROLE_EXTRACT_ENDPOINT=CHAT` 而 online 槽 base_url 为空 → 阶段2 契约提取
  回退阶段1，候选 verification=unknown 全部 OBSERVING 不晋升（promotion/qa=0%）。
  这是配置现状的如实呈现：要启用完整晋升链路需给 CHAT/MEMORY 槽配置可用端点。
  fabrication 规则（4-gram 交集）对模型改写句式保守误报（如「我叫小艾」被改写为
  「希望被称为小艾」会判编造）——口径是「无原文依据」的保守代理，读报告时须知。

### PersonaMem 公开测试集（英文域外部参照）

```bash
python scripts/fetch_personamem.py       # HF revision pin + sha256 manifest + NOTICE
python scripts/adapt_personamem.py       # 固定 seed 抽样 → 检索层用例（默认 200 行）
python -m memory.benchmark --dir memory/benchmark/_public/personamem/adapted --gate
```

数据（CC-BY-4.0，GPT-5 合成）落 `memory/benchmark/_public/`（gitignore 不入库）。
**结论限定**：英文域外部参照，不得外推中文 QQ 群聊检索质量。CI job
`memory-benchmark-public` 固定 seed 子集跑门禁；下载失败显式红/跳过，不静默绿。

### 探针的盲区

> 探针**直接把窗口消息拼成文本喂给模型**，不经过 `record_message` / `group_messages`。因此它能验证「模型能不能从消息里提取」，**不能验证「消息有没有被记录进库」**。
>
> 2026-08-17 的缺陷正落在这个盲区里：@ 消息因监听器优先级被 `block=True` 拦截而从未入库，5 个正例探针全绿，线上却一条 `AT_MENTION` 都没有、@ 对话的内容完全学不到。
>
> 入库链路只能靠两件事验证：
>
> ```sql
> -- 启动日志也会输出这个分布
> SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind;
> ```
>
> 以及真实对话后检查整合日志里的 `AT_MENTION 来源 N 条`。若 `AT_MENTION` 长期为 0 而 `BOT_SELF` 大于 0，说明落库被拦截。
