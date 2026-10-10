# LLM 成本控制

中文 | [English](llm-budget.en.md) · [文档总览](../README.md)

在线端点按 token 计费，而记忆域（整合 / 压缩 / 提取）是高频后台任务——**不记账就不知道钱花在哪，没有预算就没有上限**。成本控制分三层，越靠前越便宜：

| 层 | 手段 | 落点 |
|---|---|---|
| 结构 | 加大批量、去掉重叠窗口、收紧输出上限 | `CONSOLIDATION_ONLINE_*`（只在 CONSOLIDATION 落在在线端点时生效） |
| 前置过滤 | 纯本地零成本预筛，够废的批次干脆不调 LLM | `memory/cost_gates.py` |
| 记账与预算 | 日账落库 + 每日上限 + 超额动作 | `core/llm/usage_store.py` |

### 记账链路

```
LLM 后端（lm_studio / openai_client）
    ↓  每次调用上报一条 UsageRecord（token 数 / 缓存命中 / 截断 / 失败）
core/llm/usage_sink.py            ← 上报口：全程吞异常、零 DB 依赖
    ↓  set_sink() 挂上
core/llm/usage_store.py           ← 内存缓冲，按行数/时间节流 UPSERT
    ↓
llm_usage_daily  (date, role, slot, model)
```

**为什么中间要隔一个 sink**：记账绝不能成为聊天链路的失败点。`usage_sink` 是纯内存的上报口，不认识 SQLite、全程吞异常；`usage_store` 才是唯一的写者，它自己也把 `flush()` 写成「不抛异常、连不上库就返回 0」。最坏情况是账目少了一段，而不是群里没人收到回复。

**为什么不在每次调用里同步写库**：一次整合 20 秒、一次聊天 2 秒，中间插一次 fsync 是纯粹的浪费，多群并发时还会互相抢库锁。增量攒在内存里，攒够 16 行或过了 60 秒才落一次，读取快照与进程退出时强制落一次。

**日期键而不是计时器**：键取本地时区的 `%Y-%m-%d`，因此预算在零点自然翻滚——用计时器的话，「每日预算」会变成「每次启动后的 24 小时」，重启一次就能刷新额度。进程启动时从表里读回**今日**累计，所以重启不清零。同一次读回时顺手清掉 90 天前的旧账（天数写死，不给配置项）。

**缓存命中率的分母是输入 token，不是调用次数**：一次长请求命中一半与两次短请求各命中全部，省下的钱完全不同。这个数字是验证厂商前缀缓存到底有没有生效的唯一手段，长期为 0 说明 prompt 的固定前缀被破坏了。`tests/test_prompt_cache_prefix.py` 守着前缀顺序，用量面板守着实际效果，两者缺一不可。

### 预算在哪里生效

判据是 `usage_store.budget_blocked(role)`——放行返回 `None`，拦下返回一句可直接写进日志的原因。它**显式写在各域入口**，而不是塞进 `registry.backend_for()`：那里有实例缓存，且被大量测试 monkeypatch，把策略藏进构造函数会让「为什么这个调用没发生」变得不可追。

| 动作 | 拦哪里 |
|---|---|
| `pause_memory`（默认） | `consolidate_group()` 调 `_generate` 之前、`_extract_candidates()` 入口、`compact_once()` 入口 |
| `pause_all` | 以上三处 + `ai_gateway` 的回复生成前（`pipeline.run(ctx)` 之前） |
| `warn_only` | 不拦任何调用，每天在日志里告警一次 |

默认动作只碰记忆域三个角色，聊天链路一行不改——**超额之后群里照常能说话**，代价只是记忆暂时不更新。`pause_all` 是用户显式选择的硬停：被拦下的消息走 NoneBot 的正常「不回复」返回路径，**静默、不抛异常、不发提示句、也不回落到本地端点**。回落会让「全停」名不副实，而纯在线部署本来就没有本地端点可落。

### 前置过滤：跳过是攒批，不是丢弃

`memory/cost_gates.py` 全是**无 DB、无 I/O 的纯函数**：图片刷屏与单字应答的判定、@ 消息占比、与上一批摘要的语义新颖度（有向量走 `EmbeddingService`，取不到向量落回 `text_similarity` 的词面判据——`MEMORY_EMBEDDING_ENABLED` 默认关闭，没有这条回落这道闸在默认配置下永远不触发）。

**所有跳过路径都不推进 checkpoint**。这条是硬约束：推进了就是「消息永久丢失」的另一种形态。代价是某个只有图片刷屏的群会无限滞留，于是 `consolidation_state.skip_streak` 记连续跳过次数，达到 `CONSOLIDATION_MAX_SKIP_STREAK` 就强制整合一次并清零——最坏情况只是延迟，不是丢失。

### 400 不降级

降级链（P2）只对「换个端点就可能成功」的故障有意义：鉴权失败、额度用尽、限流、5xx、连接失败与超时。请求体本身错了（400，以及模型名写错的 404）换端点一样错，降级只会把配置问题掩盖成「有时候慢一点」。

`core/llm/registry.py` 的 `fallback_worthy(exc)` 是这条契约的唯一执行者：4xx（除鉴权/限流）返回 `False`，`RoleBackend` 见 `False` 就原样抛出并打一条点名「按契约不降级」的 error 日志，让真因冒到日志最上层。非 HTTP 异常一律可降级。

降级还要区分两种状态：`RoleBinding.describe()` 给的是**配置态**（配了哪个降级槽），`RoleBackend.runtime_state()` 给的是**运行期**（此刻是否正走降级链、冷却还剩几秒）。后者只存在于 Bot 进程的内存里——`registry.fallback_states()` 读的是 `_backends` 缓存，`deploy doctor` 自己的进程里那必然是空的，所以 doctor 从状态接口取它，而不是本地算。
