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
