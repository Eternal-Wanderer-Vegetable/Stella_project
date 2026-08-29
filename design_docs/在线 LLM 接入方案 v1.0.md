# 在线 LLM 接入方案 v1.0

> 状态：已评审，Q1 已定（见 §11.1）；Q2–Q6 记为待实测项。**本文档不含代码改动。**
> 日期：2026-08-28
> 目标：让 Stella 在「本地 LM Studio / 在线 OpenAI 兼容 API」之间无缝切换，embedding 恒定本地运行。
> 厂商立场：**通用 OpenAI 规范，不绑定厂商**；DeepSeek 仅为验收参考厂商。约束见 §4.3，守卫见 §9.1。

---

## 0. 需求与已定决策

### 0.1 需求

| # | 需求 | 来源 |
|---|---|---|
| R1 | 「记忆整合」与「对话生成」使用**两个不同的 API key**，以提高缓存命中率 | 用户 |
| R2 | embedding 模型**恒定本地运行**，与接的是在线 LLM 还是本地 SLM 无关 | 用户 |
| R3 | 无缝切换本地/在线，配置经 GUI 完成 | 用户 |

### 0.2 已定决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | **完全分角色配置**（每个 LLM 角色独立选端点、模型、温度、预算） | 配置项虽多，但可由 GUI 封装 + 详细说明弥补，且便于调试 |
| D2 | **会话压缩归「记忆整合」key** | 提高缓存命中率、减少花费 |
| D3 | 护栏三项**全做**：并发度可配 + 失败降级回本地 + 每日 token 预算 | 后台整合是持续流量 |
| D4 | 整合环节要**尽可能省钱**——多数用户无法部署本地 SLM，只能本地跑 embedding | 见第 5 章 |
| D5 | **厂商中立**：按通用 OpenAI 规范设计，不绑定厂商；换厂商只改 `.env`，不改代码 | 约束见 §4.3，自动守卫见 §9.1，验收厂商为 DeepSeek |

---

## 1. 现状盘点

### 1.1 七个模型调用点

| 角色 | 构造位置 | 当前配置键 | 闸门资源 | 备注 |
|---|---|---|---|---|
| 主对话生成 | `stella_project/plugins/bot_main/ai_gateway.py:154` | `LM_STUDIO_*` | chat | |
| 会话压缩 | `memory/session_compact.py:90` | `LM_STUDIO_BASE_URL/MODEL` | chat | **未传 api_key** |
| Router L2 兜底 | `capability/router/fallback.py:176` | `LM_STUDIO_*` | chat | |
| 记忆整合 阶段1 | `memory/consolidator.py:98` | `CONSOLIDATION_LM_STUDIO_*` | consolidation | |
| 候选提取 阶段2 | `memory/consolidator.py:113` | `MEMORY_EXTRACT_LM_STUDIO_*` | chat | 仅当阶段1 判定有自我披露时唤醒 |
| AstrBot 插件 LLM | `astrbot_compat/llm/provider.py:439` | `ASTRBOT_LLM_*` | chat | 走 `core/llm/openai_client.py`（支持 tools/流式/图片） |
| Embedding | `memory/embeddings.py:114` | `MEMORY_EMBEDDING_*` | chat（可关闸） | 无 api_key，天然本地 |

两套客户端并存且分工明确，本方案**不合并**它们：

- `core/llm/lm_studio.py` — `generate(prompt, system_prompt) -> str`，服务主链路与记忆链路。行为（空回复重试、`model_not_found` 提示）是实测调出来的。
- `core/llm/openai_client.py` — 透传完整 `messages` 数组、`tools`、图片块、流式，服务插件兼容层。

### 1.2 闸门现状与它的设计前提

`core/llm/scheduler.py` 的 docstring 写得很清楚：**它存在的唯一理由是「本地 LM Studio 不限并发，并发推理会互相拖慢且难以定位」**。两种资源（`chat` / `consolidation`）各自 FIFO 严格串行、彼此并行。

这个前提在在线 API 下**完全不成立**：在线 API 支持并发，强制串行只是白白拖慢数倍。护栏 A 要解决的正是这一点。

---

## 2. 阻塞项：四个必须先修的现存缺陷

这四个都不是新功能引入的，但全部压在本方案的必经之路上。**其中 P0-3 直接决定 R1 有没有意义。**

> **状态：这四项已于 2026-08-28 全部落地**（连同本节末尾 P1 清单里的 `session_compact` api_key）。
> 每项「修法」后新增的「已落地」小节记录**实际实现与原计划的差异**；汇总、验证结果与遗留项见 §10.1。
> 缺陷描述里的行号都是**修复前**的位置，作为问题记录保留，不再与当前代码对应。

### P0-1 `_env` 空值不回落默认值，导致 GUI 把「继承」写死成空

`config/settings.py:73-82`：

```python
def _env(key: str, default: str = "") -> str:
    """...
        default: 变量为空或未设置时返回的默认值。   ← 文档这么说
    """
    return os.getenv(key, default)                  ← 实现只处理「未设置」
```

`.env` 里写 `KEY=` 会让 dotenv 把它设成 `""`，于是返回 `""` 而**不是** default。

而 `stella-installer/src/config.html:226` 的 `buildAdvancedEnv()` 会把 schema 里**每一个**键都写成一行，值取 `field.default ?? ""`；偏偏 `deploy/env_schema.py:98` 的 `_default_value()` 在「默认值是另一个变量」时 `ast.literal_eval` 抛异常并返回 `""`。

两者相乘，结果就在当前 `.env:92-94`：

```
MEMORY_EXTRACT_LM_STUDIO_BASE_URL=      ← 本该继承 LM_STUDIO_BASE_URL
MEMORY_EXTRACT_LM_STUDIO_API_KEY=
MEMORY_EXTRACT_LM_STUDIO_MODEL=
```

`LMStudioBackend(base_url="")` 拼出的 `api_url` 是 `"/v1/chat/completions"`，httpx 直接抛 `UnsupportedProtocol`。**即：阶段2 候选提取当前每次调用都在失败**，然后静默回退阶段1 候选（`consolidator.py:197-200` 的 `except` 路径）。`deploy/checks.py:261` 那条检查只看模型 ID，抓不到 base_url 为空。

受影响的 8 个键（全是 `_env("X", 另一个键)` 形状）：

```
CONSOLIDATION_LM_STUDIO_BASE_URL / _API_KEY
MEMORY_EXTRACT_LM_STUDIO_BASE_URL / _API_KEY / _MODEL
ASTRBOT_LLM_BASE_URL / _MODEL / _API_KEY
```

**修法（三处协同，彻底消灭这一类）**

1. `config/settings.py` 新增 `_env_inherit(key, parent_value)`：值为空/纯空白视为「未设置」，返回 `parent_value`。把上述 8 处改用它。
2. `deploy/env_schema.py` 识别 `_env_inherit`，输出 `{"inherits": "LM_STUDIO_BASE_URL", "default": ""}`。
3. GUI 对带 `inherits` 的字段渲染成 **placeholder 提示「继承 XXX」的空输入框**，且 `buildAdvancedEnv()` **在其为空时不写这一行**（而不是写 `KEY=`）。

> 不建议直接把 `_env` 改成「空值即回落」：`LM_STUDIO_API_KEY=` 这类键的空值是**有意义的**（表示"无 key"），一刀切会让用户无法表达「整合端点故意不带 key」。

**已落地**——三处协同全部按上述修法实现：

- `config/settings.py`：新增 `_env_inherit()`，8 个键改用它。`_env()` 的语义**刻意不动**，上面那条理由依然成立。
- `deploy/env_schema.py`：识别 `_env_inherit`，输出 `{"inherits": 父键名, "default": ""}`。当前 schema 共 209 个字段，其中恰好 8 个带 `inherits`，父键与上表逐一对应。
- `stella-installer/src/config.html`：带 `inherits` 的字段渲染成 placeholder「继承 XXX」+ 小字提示，`buildAdvancedEnv()` 在其为空时**整行不写**。这些键**没有**加进 `managedKeys`——加进去会让它们在 GUI 里彻底消失，与「渲染成 placeholder 输入框」正好相反。
- 开发机 `.env` 上验证：`MEMORY_EXTRACT_LM_STUDIO_BASE_URL` 等三个键与 `CONSOLIDATION_LM_STUDIO_API_KEY` 原本都是「有这一行但值为空」，现在全部解析到父键值；显式覆盖仍然生效，且首尾空白会被 strip。**阶段2 提取因此恢复工作。** `.env.example` 无需改动（这些键在那里本来就是注释掉的）。

### P0-2 schema 因注释里出现「废弃」二字，把一个在用的键整个丢掉

`deploy/env_schema.py:89` 的判据是「描述里包含『废弃』」子串。而：

```python
# 整合统一使用本地 LM Studio（在线整合流程已废弃，见 _deprecated/core_llm_flexiweb.py），
# 数据整理任务与主聊天模型分离，避免显存/推理竞争；可指向同一实例的多模型或独立端口。
CONSOLIDATION_LM_STUDIO_BASE_URL = _env("CONSOLIDATION_LM_STUDIO_BASE_URL", LM_STUDIO_BASE_URL)
```

「在线整合流程已废弃」说的是 FlexiWeb（`_deprecated/core_llm_flexiweb.py`，一个用 Playwright 抓 DeepSeek 网页的子进程方案），**不是这个键**。但子串匹配把这个完全在用的键判为废弃 → 从 schema 剔除 → GUI 里看不见、也不写进 `.env`。这就是当前 `.env` 里根本没有这一行的原因。

讽刺的是这个误伤反而救了它（没被写空，继承还是好的）。但对本方案是硬伤：**「整合走在线」要配的第一个键，恰恰是 GUI 里唯一碰不到的那个。**

**修法**：废弃标记改为显式契约，不再靠猜。二选一：

- （推荐）在 `deploy/env_keys.py` 的 `DEPRECATED` 里登记——那里已经是「这个键还算不算数」的单一真相源，`env_schema` 直接查表；
- 或改用行内标记 `# @deprecated`，不再对自然语言做子串匹配。

**已落地**：取推荐方案——`deploy/env_schema.py` 只查 `deploy/env_keys.deprecation_reason(key)`，不再对注释做任何子串匹配。

顺带发现**第二个**同类误伤：`MEMORY_COMPRESS_LOG_PATH`。它的注释里提到「旧键已登记在 `_DEPRECATED_KEYS`」，而它自己恰恰是**替换旧键的那个新键**。两个键现在都回到 schema 里，同时也没有任何真正废弃的键漏进去——`tests/test_env_schema.py` 两头都守。

### P0-3 三个 prompt 模板把可变内容放在最前，可缓存前缀 ≈ 0

**这条决定 R1 有没有意义。** 前缀缓存只能命中「第一处差异之前」的内容。

| 模板 | 可变占位符位置 | 其后的固定内容 |
|---|---|---|
| `memory/consolidation_prompt.py:38` | `{current_summary}` 在第 40 行、`{messages}` 在第 43 行 | 约 85 行固定指令 + JSON schema |
| `memory/extraction_prompt.py:37` | `{messages}` 在第 41 行 | 约 75 行固定指令 |
| `memory/session_compact.py:49` | `{existing}` 第 50 行、`{messages}` 第 52 行 | 约 12 行固定要求 |

也就是说，整合 prompt 的可缓存前缀只有开头那一句（约 30 token），**后面 85 行固定指令每次全额计费，一次都缓存不上**。

量级参考：`config/settings.py:432-433` 记录了实测值「阶段2 提取 1617 prompt tokens + 280 生成」。按行数占比推算，其中固定指令约占 1000~1200 token。整合阶段1 的固定部分同量级或更多。

**修法**：模板重排为 `固定指令 + JSON schema + few-shot` → `{current_summary}` → `{messages}`（消息永远最后）。纯模板重排，不动任何逻辑。

三条配套约束（否则缓存照样打不中）：

1. 固定前缀必须**逐字节稳定**——不得含时间戳、群号、随机排序的 dict 键；
2. 前缀长度要**舒服地越过厂商的最小可缓存长度**（各家不同，有的要 1024 token 级），重排后约 1000~1200 token 是"刚好压线"，建议把 few-shot 也并进前缀把它推到安全区；
3. `system_prompt` 与 user message 的边界固定。注意整合链路目前是 `backend.generate(prompt)` 单参调用（无 system message），保持现状即可。

**已落地**：三个模板都改成「固定指令 + JSON schema + few-shot → `===== 以上为固定规则；以下是本次待分析的数据 =====` → 可变数据」，逻辑一行未动。分隔线之后只留一行输出格式提醒——这十几个 token 进不了缓存，换来「最后一条指令」的位置优势，是有意的取舍。

实测可缓存前缀（分隔线之前的固定部分；token 按 `memory/prompt_builder.estimate_tokens` 估算，非厂商实测）：

| 模板 | 固定前缀字符数 | 估算 token |
|---|---|---|
| `memory/consolidation_prompt.py` | 2871 | ≈ 2094 |
| `memory/extraction_prompt.py` | 2475 | ≈ 1538 |
| `memory/session_compact.py` | 268 | ≈ 331 |

配套约束 1、3 已满足（前缀里没有时间戳/群号；整合链路仍是单参调用）。约束 2 对整合与提取达标：2000/1500 token 舒服地越过 1024 级门槛，few-shot 已在前缀内，不必再额外堆料。

**但会话压缩不达标**：它的固定部分总共才 ≈331 token，低于常见厂商 1024 token 的起步门槛，重排对它没有实际收益（模板短，本来也不贵）。注意 D2「压缩归记忆整合 key」**救不了**这一点——前缀缓存按**前缀内容**命中，不按 key 命中，共用 key 不会让压缩蹭到整合的缓存；D2 的价值在于把记忆域流量与主聊天流量隔开，避免互相挤掉缓存。P1 若想让压缩也吃上缓存，只有让它复用整合模板的前缀，或者接受它没有缓存。

`tests/test_prompt_cache_prefix.py` 守住位置约束：把 `{messages}` 挪回模板开头，用例立刻红。

### P0-4 输出截断 → JSON 解析失败 → 推进 checkpoint → 该批消息永久丢失

`memory/consolidator.py:369-374`：

```python
parsed = self._parse_json(result)
if not parsed:
    logger.warning(f"⚠️ [Consolidator] JSON 解析失败，跳过本批次: {result[:200]}")
    # 即使解析失败也推进 checkpoint，避免同一批消息反复重处理
    self._update_checkpoint(group_id, processed_end)
    return
```

`core/llm/lm_studio.py:84-88` 的注释已经点明这个隐患。当前它相对安全（本地 `max_tokens=1200` 够用），但本方案会**放大**它：

- 第 5 章要靠「加大批量摊薄固定成本」省钱 → 输出更长 → 截断风险上升；
- 在线厂商的 `max_tokens` 语义与截断行为各异。

**修法**：区分「模型明确截断」与「输出了完整但无效的 JSON」——

- `finish_reason == "length"` → 视为**瞬时失败**：不推进 checkpoint，按更小批量重试一次；连续失败则降批量并告警。
- 其它 JSON 解析失败 → 保持今天的毒批次行为（推进 checkpoint，避免死循环）。

这需要后端把 `finish_reason` 暴露出来——与第 4.2 节的 usage 上报是同一处改动。

**已落地，且比原计划保守一档**：

- `core/llm/lm_studio.py` 新增 `generate_detailed() -> tuple[str, str]`，返回 `(回复, finish_reason)`；`generate()` 保留 `-> str` 并委托它——`-> str` 是 `LLMBackend` 的统一接口，插件兼容层等多处依赖，不动。**`finish_reason` 只经返回值传递，绝不挂到 `self` 上**：后端实例按角色共享，闸门只在单次调用期间持有，挂在 `self` 上会被另一个群的调用覆盖。
- 原计划写的是「按更小批量重试一次」，实际实现为**批量阶梯**：`_batch_ladder()` 生成最多 3 档（如 `30 → 15 → 7`，下限 5 条）。为什么不止一次：对折一次未必够；为什么不无限：在线端点每一档都是一次真实计费调用。
- 退到底仍截断 → 抛 `OutputTruncatedError`；`consolidate_group()` 在通用 `except` **之前**单独捕获它，只记 error 日志，**checkpoint 停在原地**等人改配置。非截断的 JSON 解析失败仍按毒批次推进 checkpoint（原行为保留，并在注释里注明截断不走这条路）。
- `_generate()` **保持 6 元组返回**，截断靠异常 + 内部重试传达。加第 7 个元素会打断 `test_consolidator_core.py` / `test_full_workflow.py` / `test_short_term_attribution.py` 里 5 处 monkeypatch 假后端。
- 阶段2 提取的截断只影响它自己：记日志 + 返回 `None`，回退阶段1 候选。checkpoint 由阶段1 掌管，不受影响。
- 与 §4.2 的 usage 上报**没有一起做**：P0 只暴露 `finish_reason`，usage / 命中率上报留给 P1 的 registry 改造（`prompt_tokens` 等目前仅写日志）。

### P1（非阻塞，建议一并处理）

- **`session_compact.py:90` 不传 `api_key`**：切在线后会话压缩直接 401。D2 要求它归记忆域，此处必须补上。**✅ 已在 P0 一并补上**——`_get_backend()` 现在传 `LM_STUDIO_API_KEY`；P1 改指记忆域端点时，base_url / model / api_key 三个参数一起换。
- **`consolidator.py:479` 的 overlap 是 id 减法**：`fetch_from = max(0, last_id - CONSOLIDATION_OVERLAP)`。`messages` 表 id 是跨群全局自增，所以「回看 15」实际回看到本群多少条，取决于**其它群的插入速度**——热闹时可能只回看 1~2 条，冷清时 15 条。重叠量不确定 → 在线计费不可预测。第 5.2 节直接把原文重叠改掉，此项随之消解。

---

## 3. 目标配置模型：端点 × 角色

### 3.1 为什么分两层

D1 要求「完全分角色」。但有一条**硬约束**：`deploy/env_schema.py` 是用 AST 扫 `config/settings.py` 里字面量 `_env("KEY", ...)` 调用来生成 GUI 的，因此**所有配置键必须静态声明**——动态命名的端点在 GUI 里根本不会出现。

于是采用「固定数量的端点槽 × 角色引用」：

- **端点（Endpoint）** = 一组连接参数：`base_url` + `api_key` + `kind` + `concurrency` + `timeout`。
  它同时是 **API key 的归属单位**（→ R1 天然落地）和 **闸门资源单位**（→ 护栏 A 天然落地）。
- **角色（Role）** = 引用一个端点 + 自己的 `model` / `temperature` / `max_tokens`。

R1 的两个 key 就是两个端点（`ONLINE_CHAT` / `ONLINE_MEMORY`）；「缓存域」这个概念因此在配置里有了名字，而不是靠用户记住该往哪几个角色里粘同一个 key。

### 3.2 端点槽（4 个，可扩展）

| 槽名 | 用途 |
|---|---|
| `LOCAL` | 本地 LM Studio |
| `ONLINE_CHAT` | 在线·对话域（R1 的 key A） |
| `ONLINE_MEMORY` | 在线·记忆域（R1 的 key B） |
| `EXTRA` | 备用槽（混合部署 / 调试指向第三个服务） |

每槽 5 个键：

```
LLM_ENDPOINT_<槽>_BASE_URL      # http(s):// 开头
LLM_ENDPOINT_<槽>_API_KEY       # 本地留空
LLM_ENDPOINT_<槽>_KIND          # local | online（**显式**，不再靠 api_key 猜，见 4.3）
LLM_ENDPOINT_<槽>_CONCURRENCY   # 闸门并发度：本地 1，在线默认 4
LLM_ENDPOINT_<槽>_TIMEOUT       # 秒
```

> 需要第 5 个端点时，在 `settings.py` 加 5 行即可——这是静态声明约束下的显式取舍，写在文档里而不是留给用户猜。

### 3.3 角色（6 个）

每角色 4 个键：

```
LLM_ROLE_<角色>_ENDPOINT     # LOCAL | ONLINE_CHAT | ONLINE_MEMORY | EXTRA | none
LLM_ROLE_<角色>_MODEL
LLM_ROLE_<角色>_TEMPERATURE
LLM_ROLE_<角色>_MAX_TOKENS
```

角色清单与**默认端点归属**（已按 D2 落实）：

| 角色 | 说明 | 纯本地默认 | 纯在线默认 |
|---|---|---|---|
| `CHAT` | 主对话生成 | `LOCAL` | `ONLINE_CHAT` |
| `ROUTER` | Router L2 兜底 | `LOCAL` | `ONLINE_CHAT` |
| `PLUGIN` | AstrBot 插件 LLM | `LOCAL` | `ONLINE_CHAT` |
| `COMPACT` | 会话压缩 | `LOCAL` | **`ONLINE_MEMORY`** ← D2 |
| `CONSOLIDATION` | 记忆整合 阶段1 | `LOCAL_MEM`\* | `ONLINE_MEMORY` |
| `EXTRACT` | 候选提取 阶段2 | `LOCAL` | `ONLINE_MEMORY` |

\* 纯本地时整合与聊天要走**两个独立闸门**（这是今天 `RESOURCE_CHAT` / `RESOURCE_CONSOLIDATION` 分离的原因：27B 跑 GPU、E4B 跑 CPU，可真正并行）。做法是把 `EXTRA` 槽当作 `LOCAL_MEM` 使用——同一个 `base_url`，独立闸门。**行为与今天完全一致。**

`ENDPOINT=none` 表示该角色停用（见 5.5 极省档）。

### 3.4 Embedding 的特殊地位（R2）

embedding **不进入端点/角色体系**，保留 `MEMORY_EMBEDDING_*` 原样，并在注释与 GUI 里明确「本地专用，不随 LLM 切换」。

唯一需要改的是它的闸门归属。今天 `LLM_SCHEDULER_GATE_EMBEDDING=true`（默认）把 embedding 挂在 chat 闸门上，理由是「embedding 默认与主聊天同实例」。**一旦对话切到在线，这个默认值就变成一个陷阱**：本地 embedding 会去排在线调用的队，白白串行。

改为：

```
MEMORY_EMBEDDING_GATE = auto | <端点槽名> | none      # 取代 LLM_SCHEDULER_GATE_EMBEDDING
```

`auto` 的判定是确定性的、可打印的：**若存在 `KIND=local` 且 `BASE_URL` 与 `MEMORY_EMBEDDING_BASE_URL` 相同的端点槽 → 共用该槽闸门；否则独立不排队。** doctor 输出解析结果，避免"魔法"。

### 3.5 三个场景的完整配置

**场景 A — 纯本地（等价今天的行为）**

```ini
LLM_ENDPOINT_LOCAL_BASE_URL=http://127.0.0.1:1234
LLM_ENDPOINT_LOCAL_KIND=local
LLM_ENDPOINT_LOCAL_CONCURRENCY=1
LLM_ENDPOINT_EXTRA_BASE_URL=http://127.0.0.1:1234     # 同址、独立闸门 = 今天的 consolidation 资源
LLM_ENDPOINT_EXTRA_KIND=local
LLM_ENDPOINT_EXTRA_CONCURRENCY=1

LLM_ROLE_CHAT_ENDPOINT=LOCAL
LLM_ROLE_CHAT_MODEL=google/gemma-4-26b-a4b-qat
LLM_ROLE_ROUTER_ENDPOINT=LOCAL
LLM_ROLE_PLUGIN_ENDPOINT=LOCAL
LLM_ROLE_COMPACT_ENDPOINT=LOCAL
LLM_ROLE_EXTRACT_ENDPOINT=LOCAL
LLM_ROLE_CONSOLIDATION_ENDPOINT=EXTRA
LLM_ROLE_CONSOLIDATION_MODEL=google/gemma-4-e4b

MEMORY_EMBEDDING_BASE_URL=http://127.0.0.1:1234
MEMORY_EMBEDDING_GATE=auto                             # → 解析为 LOCAL
```

**场景 B — 纯在线 + 本地 embedding（R1/R2 的主场景，多数用户）**

```ini
LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=https://api.example.com
LLM_ENDPOINT_ONLINE_CHAT_API_KEY=sk-aaaa                # ← 对话生成 key
LLM_ENDPOINT_ONLINE_CHAT_KIND=online
LLM_ENDPOINT_ONLINE_CHAT_CONCURRENCY=4

LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL=https://api.example.com
LLM_ENDPOINT_ONLINE_MEMORY_API_KEY=sk-bbbb              # ← 记忆整合 key（独立缓存域）
LLM_ENDPOINT_ONLINE_MEMORY_KIND=online
LLM_ENDPOINT_ONLINE_MEMORY_CONCURRENCY=2

LLM_ROLE_CHAT_ENDPOINT=ONLINE_CHAT
LLM_ROLE_CHAT_MODEL=<强模型>
LLM_ROLE_ROUTER_ENDPOINT=ONLINE_CHAT
LLM_ROLE_ROUTER_MODEL=<廉价模型>                          # 兜底判定是二分类，不需要强模型
LLM_ROLE_PLUGIN_ENDPOINT=ONLINE_CHAT

LLM_ROLE_COMPACT_ENDPOINT=ONLINE_MEMORY                 # D2
LLM_ROLE_COMPACT_MODEL=<廉价模型>
LLM_ROLE_CONSOLIDATION_ENDPOINT=ONLINE_MEMORY
LLM_ROLE_CONSOLIDATION_MODEL=<廉价模型>                   # 阶段1 是总结任务
LLM_ROLE_EXTRACT_ENDPOINT=ONLINE_MEMORY
LLM_ROLE_EXTRACT_MODEL=<强模型>                           # 阶段2 是高精度抽取，但低频

MEMORY_EMBEDDING_BASE_URL=http://127.0.0.1:1234         # 恒定本地
MEMORY_EMBEDDING_GATE=auto                              # → 无本地 LLM 端点，解析为 none（不排队）
```

**场景 C — 混合：对话在线、整合本地（有本地 SLM 的用户，最省钱）**

```ini
LLM_ROLE_CHAT_ENDPOINT=ONLINE_CHAT
LLM_ROLE_ROUTER_ENDPOINT=ONLINE_CHAT
LLM_ROLE_PLUGIN_ENDPOINT=ONLINE_CHAT
LLM_ROLE_COMPACT_ENDPOINT=LOCAL
LLM_ROLE_CONSOLIDATION_ENDPOINT=LOCAL
LLM_ROLE_EXTRACT_ENDPOINT=LOCAL
```

---

## 4. 代码改造点

### 4.1 新增 `core/llm/registry.py`

单一入口，取代 6 处各自读配置的构造代码：

```python
ROLE_CHAT = "chat"; ROLE_COMPACT = "compact"; ROLE_ROUTER = "router"
ROLE_CONSOLIDATION = "consolidation"; ROLE_EXTRACT = "extract"; ROLE_PLUGIN = "plugin"

def endpoint_of(role: str) -> Endpoint | None   # 解析角色→端点；none 时返回 None
def backend_for(role: str) -> LLMBackend | None # 构造/缓存 LMStudioBackend（带 role 标签）
def gate_of(role: str) -> str                   # 闸门资源名（= 端点槽名）
def describe() -> dict                          # 供 doctor / GUI / 启动日志打印解析结果
```

- 端点/角色解析在**启动时一次性完成并校验**（url 协议、槽名合法、`online` 必须有 key、模型非空），失败即 `deploy doctor` 报错，而不是运行到第一次调用才 500。
- `describe()` 在启动日志打一张表：哪个角色 → 哪个端点 → 哪个模型 → 哪个闸门。这是"无缝切换"能被信任的前提。

**六处构造点改为**：

| 文件:行 | 改为 |
|---|---|
| `ai_gateway.py:154` | `pipeline.set_llm_backend(backend_for(ROLE_CHAT))` |
| `session_compact.py:90` | `backend_for(ROLE_COMPACT)`（顺带修 P1 的 api_key 缺失） |
| `fallback.py:176` | `backend_for(ROLE_ROUTER)` |
| `consolidator.py:98` | `backend_for(ROLE_CONSOLIDATION)` |
| `consolidator.py:113` | `backend_for(ROLE_EXTRACT)` |
| `provider.py:439,481` | 端点参数取 `endpoint_of(ROLE_PLUGIN)`（仍用 `openai_client`，不改客户端） |

`acquire(RESOURCE_CHAT, ...)` 的 5 处调用点改为 `acquire(gate_of(role), ...)`。`RESOURCE_CHAT` / `RESOURCE_CONSOLIDATION` 与 `chat_llm_lock` / `consolidation_llm_lock` 保留为兼容别名（`core/llm/__init__.py` 已有这个模式）。

### 4.2 `LMStudioBackend`：增加 role 标签与响应元数据上报

`core/llm/openai_client.py` 的 docstring 明确「不去动 `LMStudioBackend.generate()`」，其行为是实测调出来的。因此**不改签名、不改返回类型、不改重试逻辑**，只做加法：

```python
LMStudioBackend(..., role="consolidation")   # 新增可选参数
```

`generate()` 内部本已解析 `finish_reason` 与 `usage`（`lm_studio.py:81-82`），只是丢掉了。改为在成功分支额外调用一次模块级记录器：

```python
usage_sink.record(role=self.role, model=self.model, usage=usage, finish_reason=finish)
```

`generate()` 的返回值仍是 `str`。这一处同时供给 P0-4（`finish_reason`）、护栏 C（token 记账）、GUI 用量面板——一次改动三处收益。

`openai_client.py` 同样加 `role` 参数并上报。

### 4.3 参数兼容层：厂商中立，不得出现「换一家就跑不通」

**这是一条硬约束，不是"尽量"。** 方案按通用 OpenAI Chat Completions 规范设计，不绑定任何厂商；DeepSeek 只是参考验收厂商，其行为**不得**渗进主链路。

三条落地规则：

**① 最小合规请求体原则**

默认只发 OpenAI 规范里近乎普适的字段：`model` / `messages` / `temperature` / `max_tokens`（流式加 `stream`，插件链路加 `tools` / `tool_choice`）。

任何"锦上添花"的字段——`reasoning_effort`、`response_format`、`stream_options`、各家私有的思考开关——**一律必须有显式端点级开关，且默认关闭**。`_build_payload`（`openai_client.py:36`）目前基本已符合，唯一的违规者就是下面这个：

```python
if not self.api_key:                        # 「没 key 就是本地」
    payload["reasoning_effort"] = "none"
```

`lm_studio.py:66` 与 `openai_client.py:62` 共用这个启发式，它在两个方向上都会错：本地服务要求 dummy key 时不发（本地推理模型会把 token 全耗在思维链上导致 content 为空），在线服务不需要 key 时误发（某些厂商直接 400）。

**改为读端点的显式 `KIND`：只有 `kind == "local"` 才发 `reasoning_effort=none`。** 这恰好是"换厂商跑不通"的典型样本——一个为本地模型加的字段，被一条猜测式判据泄漏到了在线请求里。

> `openai_client.chat_completion` 已有的 `extra_body` 参数不受此约束：它是**调用方显式传入**的插件私有参数，责任在调用方，不是主链路默认行为。

**② 差异靠错误自适应，不靠厂商白名单**

厂商白名单必然过时（新厂商、旧厂商改版都会漏），因此差异处理一律做成「**按错误体自适应 + 记住结果**」，白名单只作为可选的预置加速：

| 差异 | 处理 |
|---|---|
| `max_tokens` vs `max_completion_tokens` | 400 且错误体命中该关键词 → 自动切换字段名重试并在端点上记住 |
| 部分推理模型拒绝 `temperature` | 400 且错误体命中 → 省略该字段重试并记住 |
| 不支持 `tools` / `function calling` | 插件链路降级为无工具模式并告警（`astrbot_compat` 已有截断/告警惯例） |
| 流式 `[DONE]` / 心跳行 / 空 chunk 差异 | `openai_client.py:217-226` 已容错，保持 |
| 错误体结构差异（`error.message` 嵌套层级各家不同） | 只做关键词匹配，不解析固定结构 |

注意这套自适应必须与 `lm_studio.py:112` 现有的「4xx 不重试」判据协调：**4xx 原则上不重试，但"已识别出可修正的参数差异"是唯一例外，且同一请求最多自适应重试一次**，避免退化成对配置错误的无限重试。

**③ 不依赖任何厂商的结构化输出能力**

整合/提取/压缩三条链路都要求 JSON。**不得**把正确性押在 `response_format` / JSON mode 上——不是所有兼容端点都支持。继续依赖 `consolidator._parse_json` 的既有容错（它已能处理代码块包裹与前后杂文，`commands.rs:746` 的 `extract_json` 是同一思路的 Rust 版）。`response_format` 只作为**可选**的端点开关，用于在支持的厂商上省几个 token，关闭时行为不变。

### 4.4 闸门：FIFO 串行 → 可配置并发度（护栏 A）

`core/llm/scheduler.py` 现在每个资源一把 `asyncio.Lock`。改为 `asyncio.Semaphore(concurrency)`，`concurrency` 取自端点：

- 本地端点 `concurrency=1` → **行为与今天逐字一致**（Semaphore(1) ≡ Lock）；
- 在线端点默认 4。

`snapshot()` 的统计口径要跟着调整（`holder` 从单值变成集合，`waiting` 语义不变）。
docstring 必须改写——它现在说的是「LM Studio 不限并发所以应用层必须串行」，改为「闸门是**端点级**并发上限：本地=1 因为共享模型会互相拖慢；在线=N 因为要贴合厂商限流」。

`LLM_SCHEDULER_PRIORITY_ENABLED` 保持未实现状态（今天就是 FIFO + 打一条 debug），本方案不动它。

**「绝不能同时持有两把闸门」这条铁律必须保留**——`consolidator` 用群级锁把「阶段1」与「阶段2」拆成两个不嵌套的持有窗口，正是为此。在线化后跨端点持有的后果同样是队头阻塞。

### 4.5 失败降级（护栏 B）

在 `registry` 层加一个**降级链**，而不是在每个调用点写 try：

```
LLM_FALLBACK_ENABLED=true
LLM_ROLE_<角色>_FALLBACK_ENDPOINT=      # 留空=不降级
LLM_FALLBACK_COOLDOWN=300               # 秒；降级后多久再试主端点
```

触发条件：401/403（鉴权）、429（限流）、5xx 重试耗尽、连接超时。**4xx 中的 400（请求体错误）不降级**——那是配置问题，降级只会掩盖它（这与 `lm_studio.py:112` 现有的「4xx 不重试」判据一致）。

降级期间打 warning 并在 GUI 状态页显示。冷却到期后自动试探性回归。

---

## 5. 成本控制（D4：整合环节尽可能省钱）

### 5.1 先看成本从哪来

一次整合调用的输入成本 = **固定 prompt 成本**（约 85 行指令 + JSON schema）+ **变动消息成本**（本批消息 + 重叠）。

关键事实：**固定部分与批量大小无关**。所以

> 每条消息摊到的固定成本 = 固定 prompt 成本 ÷ 批量大小

当前配置（`CONSOLIDATION_LOCAL_BATCH_SIZE=30`）下固定部分占比已经很高；而 **force 路径（`CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE=10`，@触发/主动发言前）用 1/3 的批量付同一份固定成本，是全链路单位成本最高的路径**。`PROACTIVE_COOLDOWN=600` 意味着最多 144 次主动发言/天，每次都可能带一次 force 整合。

三个杠杆因此排定：**① 让固定成本进缓存 → ② 摊薄固定成本 → ③ 减少不必要的调用**。

### 5.2 Tier 0：结构性省钱（无功能损失，优先做）

| # | 措施 | 预计效果 | 实现成本 |
|---|---|---|---|
| T0-1 | **prompt 前缀重排**（P0-3）：固定指令与 schema 前置，`{messages}` 永远最后 | 固定部分从"每次全价"变成"缓存价"。这是**唯一一条能让 R1 的双 key 真正生效**的措施 | 低（纯模板重排） |
| T0-2 | **取消原文重叠，改为摘要延续**：`CONSOLIDATION_OVERLAP` 在线端点下置 0；话题连续性由已在传的 `current_summary`（阶段1 输出的 `active_summary`）承载 | 省掉每批重复计费的重叠消息；顺带消解 P1 的 id 减法不确定性 | 低 |
| T0-3 | **阶段1 用廉价模型、阶段2 用强模型**：阶段1 是"总结 + 二分类判断"，阶段2 才是高精度抽取，且仅在 `has_self_disclosure=true` 时唤醒（`consolidator.py:389`） | 把大部分调用量压到廉价模型上 | 零（3.3 的分角色配置天然支持） |
| T0-4 | **输出瘦身**：在线端点下收紧 `LLM_ROLE_CONSOLIDATION_MAX_TOKENS`，并在 schema 里去掉冗余字段 | 输出 token 通常比输入贵数倍 | 低，**但必须先修 P0-4**，否则截断=丢消息 |
| T0-5 | **force 路径批量对齐**：在线端点下把 `FORCE_BATCH_SIZE` 提到与常规批量同级，或允许 force 路径直接复用上一次的短期摘要而不触发新调用 | 消掉单位成本最高的那条路径 | 中（需确认 @ 响应延迟可接受） |

**缓存 TTL 与批量的张力（重要）**

多数厂商的前缀缓存有分钟级 TTL（以厂商文档为准）。`CONSOLIDATION_SCHEDULE_INTERVAL=120` 恰好落在常见 TTL 内，所以整合前缀能保持热。

但这意味着：**5.3 的"合批省钱"不能靠拉长间隔来实现**——间隔一旦超过 TTL，固定成本就从缓存价回到全价，反而更贵。

> 结论：**加大批量、不要拉长间隔。** 间隔建议保持 ≤ 4 分钟，通过提高 `BATCH_SIZE` 和"不足门槛不整合"来摊薄。

### 5.3 Tier 1：本地免费预筛（用户明确可本地跑 embedding，这是免费算力）

| # | 措施 | 依据 |
|---|---|---|
| T1-1 | **来源占比门控**：一批消息里 `AT_MENTION` 占比为 0、且其余全是图片/表情/单字附和时，跳过本批（**不推进 checkpoint**），攒到下一轮 | `settings.py:347` 的实测结论：「群聊主体为角色扮演，被动摄入的可提取信息极少」，且 AT_MENTION 是唯一稳定信息源。`_fetch_next_messages` 已经返回 `at_senders`，判据现成 |
| T1-2 | **阶段2 只喂 AT_MENTION 消息**：`_extract_candidates` 目前收整批 `messages_text`；改为只传 AT_MENTION 及其上下文 | 阶段2 的任务定义就是"用户亲口说的关于自己的信息"，被动刷屏对它无用却全额计费 |
| T1-3 | **语义新颖度门控**（本地 embedding，零成本）：本批消息与 `short_term_context.active_summary` 的余弦相似度高于阈值 → 话题没推进、无新信息 → 跳过并攒批 | `memory/embeddings.py` 的 `similarity()` 现成；注意 `MEMORY_EMBEDDING_ENABLED` 默认 `false`，在线模式下应默认开启 |
| T1-4 | **词面重复率预筛**（零成本，无需 embedding）：`memory/text_similarity.py` 的 `is_similar` 现成，可作为 T1-3 的降级路径 | 免依赖 |
| T1-5 | **攒批门槛**：新消息不足 N 条不整合（force 路径除外），N 在线默认远高于本地 | 直接摊薄固定成本 |

> **所有"跳过"路径都必须不推进 checkpoint**，否则就是 P0-4 的另一种形态（消息永久丢失）。跳过 = 攒批，不是丢弃。需要一个"连续跳过上限"兜底，避免某群永远攒不够而无限滞留。

### 5.4 Tier 2：预算与记账（护栏 C）

```
LLM_USAGE_ACCOUNTING=true
LLM_DAILY_TOKEN_BUDGET=0                 # 0=不限
LLM_BUDGET_SCOPE=online                  # 只计在线端点
LLM_BUDGET_EXHAUSTED_ACTION=pause_memory # pause_memory | pause_all | warn_only
```

- 记账数据来自 4.2 的 `usage_sink`，落 SQLite（新表，走 `memory/schema.py` + `memory/migrations.py` 的既有迁移机制）。按 `(日期, 角色, 端点, 模型)` 聚合输入/输出/缓存命中 token。
- **超额时默认只停记忆域（整合/压缩/提取），对话照常可用**——这是"钱花光了 Bot 还能说话"与"记忆停止更新"之间的正确取舍。
- 缓存命中率必须单独统计并在 GUI 展示：**这是验证 R1 与 T0-1 是否真的生效的唯一手段**。若厂商在 `usage` 里返回缓存字段则直读，否则用"输入 token 数相对基线的下降"间接观测。
- 每日重置按本地时区；跨天边界与 `CONSOLIDATION_SCHEDULE_INTERVAL` 的定时任务解耦（用日期键而非计时器）。

### 5.5 Tier 3：极省档

| 档 | 配置 | 后果 |
|---|---|---|
| 降频档 | 提高攒批门槛 + 加大批量 | 记忆更新延迟上升，成本线性下降 |
| 停整合档 | `LLM_ROLE_CONSOLIDATION_ENDPOINT=none` | 整合与候选晋升停止；短期摘要不再更新。检索仍可用（本地 embedding + 原始消息尾巴），但长期记忆不再增长 |
| 混合档 | 场景 C：整合回本地 SLM | 在线成本仅剩对话，**这是有本地算力用户的最优解**，值得在 GUI 里显式推荐 |

`ENDPOINT=none` 时所有调用点必须优雅退化而非抛异常——`fallback.py:170` 已有「构造失败返回 None → 兜底不可用即降级」的先例，沿用该惯例。

### 5.6 省钱杠杆总排序

| 优先 | 措施 | 效果 | 成本 | 风险 |
|---|---|---|---|---|
| 1 | T0-1 prompt 前缀重排 | 极高（且是 R1 的前提） | 低 | 需回归验证输出质量不变 |
| 2 | T0-2 取消原文重叠 | 高 | 低 | 话题连续性需实测 |
| 3 | T0-3 阶段分层用模型 | 高 | 零 | 阶段1 廉价模型的 JSON 稳定性需实测 |
| 4 | T1-1/T1-2 来源门控 | 高 | 中 | 漏整合 → 需连续跳过上限兜底 |
| 5 | T1-5 攒批门槛 | 中高 | 低 | 记忆延迟 |
| 6 | T0-4 输出瘦身 | 中 | 低 | **必须先修 P0-4** |
| 7 | T1-3 语义新颖度门控 | 中 | 中 | 阈值需标定，可用 `memory/benchmark/` |
| 8 | T0-5 force 路径对齐 | 中 | 中 | @ 响应延迟 |

---

## 6. GUI 设计

### 6.1 配置页新增「模型服务」分区

`stella-installer/src/config.html` 当前的主表单把模型配置写死成三个字段（`lm_base_url` / `chat_model` / `consolidation_model` / `embedding_model`），由 `ConfigInput`（`commands.rs:96`）→ `deploy init --answers`（`init_wizard.Answers`）→ `render_env` 落盘。这条链路要相应扩展。

新分区两块：

**① 端点卡片**（4 张，每张：地址 / API key / 类型 local·online / 并发度 / 超时 / 「测试连接」按钮）

- 「测试连接」= 调 `/v1/models`（在线厂商普遍支持）→ 成功则把返回的模型列表灌进该端点的 `datalist`，供角色矩阵选择。现有 `list_models`（`commands.rs:245`）已实现这个形状，只需支持带 `api_key` 与任意 `base_url`。
- 在线端点若 API key 为空 → 前端即时拦截（对应 4.1 的启动校验）。

**② 角色矩阵**（6 行 × 4 列：角色 | 端点下拉 | 模型下拉 | 温度 | max_tokens）

- 每行带一句人话说明（「会话压缩：把较早的对话压成回顾。默认归记忆域，与整合共用缓存以省钱」）。
- 顶部三个**一键预设**：`纯本地` / `纯在线（双 key）` / `混合（对话在线·整合本地）`，对应 3.5 的三个场景。这是 D1「配置项多，用 GUI 封装弥补」的落点——用户默认只点预设，展开才见细节。
- Embedding 单独一行，**端点列灰显并注明「本地专用，不随 LLM 切换」**（R2 在界面上的兑现）。

### 6.2 用量面板

`run.html` 增一块：今日 token（按角色/端点/模型）、缓存命中率、预算余量、当前降级状态。数据来自 5.4 的记账表。

**缓存命中率是本方案的验收指标**，必须可见 —— 否则 R1 是否生效无从判断。

### 6.3 schema 自动生成需要的配套

- 在 `config/settings.py` 新增两个章节注释（`# ---------- LLM 端点 ----------` / `# ---------- LLM 角色 ----------`），`env_schema._sections_by_line` 会自动分组。
- `config.html:33` 的 `managedKeys` 要补上全部新键，否则主表单管的键会在「高级配置」里重复出现一份。
- P0-1 的第 3 步（带 `inherits` 的字段留空时不写入 `.env`）必须同期落地。
- P0-2 修完后 `CONSOLIDATION_LM_STUDIO_BASE_URL` 会重新出现在 schema 里——它此时已是废弃别名，应正式登记进 `env_keys.DEPRECATED`。

---

## 7. doctor 检查项（`deploy/checks.py`）

现有的 `check_lm_studio_reachable` / `check_lm_model_chat` / `_consolidation` / `_extract` / `_embedding` 全部按「本地 LM Studio + `/v1/models` 列表」假设写的，需要按端点类型分流：

| 新增/改造 | 检查 |
|---|---|
| 改造 | 端点可达性：按槽逐个探测；**在线端点不能因为公网抖动就报 blocking**（沿用 `checks.py:200` 「可先启动 Bot 观察日志」的分级惯例） |
| 改造 | 模型 ID 校验：本地端点比对 `/v1/models` 列表（保留今天的模糊匹配建议）；在线端点厂商列表可能极长或不含私有模型 → 降为 warn |
| 新增 | 角色→端点映射完整性：槽名合法、被引用的槽已配 `BASE_URL`、`KIND=online` 必须有 `API_KEY` |
| 新增 | **R2 守卫**：`MEMORY_EMBEDDING_BASE_URL` 指向非本地地址时 warn（「embedding 应本地运行」） |
| 新增 | **缓存前缀健康度**：检测三个 prompt 模板中占位符是否位于固定指令之前（P0-3 回归守卫）——这条能防止将来有人改 prompt 时把缓存优化改回去 |
| 新增 | 预算/记账表存在且可写；今日用量与降级状态摘要 |
| 新增 | 双 key 配置提示：`ONLINE_CHAT` 与 `ONLINE_MEMORY` 的 `API_KEY` **相同**时 warn——这会让 R1 的缓存隔离失效，是最容易犯的配置错误 |
| 新增 | 废弃键提示：检测到旧 `LM_STUDIO_*` / `CONSOLIDATION_LM_STUDIO_*` 等仍在 `.env` 里 → 提示已迁移（走 `check_deprecated_env_keys` 现成机制） |

---

## 8. 迁移与兼容

### 8.1 键映射

`deploy/env_keys.py` 的 `RENAMED` 只处理**值可直接沿用**的 1:1 改名，正好适用大部分：

| 旧键 | 新键 |
|---|---|
| `LM_STUDIO_BASE_URL` | `LLM_ENDPOINT_LOCAL_BASE_URL` |
| `LM_STUDIO_API_KEY` | `LLM_ENDPOINT_LOCAL_API_KEY` |
| `LM_STUDIO_MODEL` | `LLM_ROLE_CHAT_MODEL` |
| `CONSOLIDATION_LM_STUDIO_MODEL` | `LLM_ROLE_CONSOLIDATION_MODEL` |
| `CONSOLIDATION_LM_STUDIO_TEMPERATURE` | `LLM_ROLE_CONSOLIDATION_TEMPERATURE` |
| `CONSOLIDATION_LOCAL_MAX_TOKENS` | `LLM_ROLE_CONSOLIDATION_MAX_TOKENS` |
| `MEMORY_EXTRACT_LM_STUDIO_MODEL` | `LLM_ROLE_EXTRACT_MODEL` |
| `MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE` | `LLM_ROLE_EXTRACT_TEMPERATURE` |
| `MEMORY_EXTRACT_MAX_TOKENS` | `LLM_ROLE_EXTRACT_MAX_TOKENS` |
| `ASTRBOT_LLM_MODEL` | `LLM_ROLE_PLUGIN_MODEL` |
| `ASTRBOT_LLM_TEMPERATURE` | `LLM_ROLE_PLUGIN_TEMPERATURE` |
| `ASTRBOT_LLM_MAX_TOKENS` | `LLM_ROLE_PLUGIN_MAX_TOKENS` |
| `LLM_TIMEOUT` | `LLM_ENDPOINT_LOCAL_TIMEOUT`（+ 其余槽默认继承） |

**不能进 `RENAMED` 的三类**，需要 `deploy/env_merge.py` 里写一小段迁移逻辑：

1. `CONSOLIDATION_LM_STUDIO_BASE_URL` / `MEMORY_EXTRACT_LM_STUDIO_BASE_URL` / `ASTRBOT_LLM_BASE_URL` → 语义从"URL"变成"槽归属"：若与 `LM_STUDIO_BASE_URL` 相同（含"因 P0-1 被写空"的情况）→ 该角色 `ENDPOINT=LOCAL`；不同 → 写入 `EXTRA` 槽。
2. `LLM_SCHEDULER_GATE_EMBEDDING`（bool）→ `MEMORY_EMBEDDING_GATE`（枚举）：`true` → `auto`，`false` → `none`。
3. **纯本地存量用户的整合闸门**：为保持"整合与聊天两个独立闸门"的现有行为，迁移时把 `EXTRA` 槽填成与 `LOCAL` 同址，并令 `LLM_ROLE_CONSOLIDATION_ENDPOINT=EXTRA`（见 3.3 脚注）。

`ASTRBOT_LLM_ENABLED` / `_SYSTEM_PROMPT` / `_MAX_CONTEXT_TOKENS` / `_MAX_TOOLS` / `_TOOL_TIMEOUT` / `_MAX_TOOL_STEPS` **保持原名**——它们是插件链路的行为参数，不是端点/模型配置。

### 8.2 兼容注意

- `astrbot_compat` 刻意通过 `settings.ASTRBOT_LLM_*` **属性访问**读配置（`manager.py:31-34` 注释：`from config import X` 会在 import 时绑死名字，测试 monkeypatch 改不动）。改名必须同步更新 `provider.py`，并保持属性访问方式。
- `_deprecated/core_llm_flexiweb.py` 与 `_deprecated/memory_online_llm.py` 是上一代在线方案（Playwright 抓 DeepSeek 网页），**与本方案无关**，不复用、不参考。settings.py:448 那句引用它的注释应改写（它正是 P0-2 的成因）。
- 升级路径必须**幂等**且在 `deploy migrate` 的干跑报告里可见（`migrate.py` 已有 `--dry-run` 与备份机制）。

---

## 9. 测试计划

沿用 `tests/` 现有布局与命名：

| 文件 | 覆盖 |
|---|---|
| `tests/test_llm_registry.py`（新） | 角色→端点解析、`none`/非法槽名/在线缺 key 的校验、`describe()` 输出、三个场景配置的解析结果 |
| `tests/test_env_inherit.py`（新，✅ 13 用例） | **P0-1 回归**：`KEY=` 空值必须回落父键值；schema 输出 `inherits`。GUI 空值不写入这一半**没有**自动化覆盖（无 JS 测试框架），改由 §9.2 第 6 项人工验证。3 个用例在父键自身为空时 skip |
| `tests/test_env_schema.py`（改，✅ 7 用例） | **P0-2 回归**：注释含「废弃」二字的在用键不得被剔除；废弃判定改走 `env_keys` 后仍正确；反向也守——真正登记废弃的键不得漏进 schema |
| `tests/test_prompt_cache_prefix.py`（新，✅ 6 用例） | **P0-3 回归**：三个模板的占位符位置必须在固定指令之后；枚举占位符须留在前缀内；分隔线之后的固定文本不超过一行 |
| `tests/test_consolidator_core.py`（改，✅ 21 用例） | **P0-4 回归**：`finish_reason=length` 时缩批重试、退到底抛 `OutputTruncatedError` 且**不得**推进 checkpoint；对照组——不可解析但未截断的输出仍推进 |
| `tests/test_lm_studio.py`（改，✅ 8 用例） | **P0-4 回归**：`generate_detailed()` 用返回值交出 `finish_reason`；`generate()` 保持 `-> str` 签名不变 |
| `tests/test_scheduler_concurrency.py`（新） | `concurrency=1` 与今天的 Lock 行为等价；`>1` 时真并发；跨端点不互相阻塞 |
| `tests/test_llm_compat.py`（新） | `reasoning_effort` 只在 `kind=local` 时发送；`max_completion_tokens` / `temperature` 的错误自适应各生效一次且只重试一次 |
| `tests/test_openai_contract.py`（新） | **厂商中立守卫**，见下 |
| `tests/test_usage_accounting.py`（新） | usage 记账聚合、日预算触发、`pause_memory` 只停记忆域 |
| `tests/test_cost_gates.py`（新） | T1-1/T1-3 跳过时**不推进 checkpoint**；连续跳过上限兜底生效 |
| `tests/test_deploy_checks.py`（改） | 新增检查项；在线端点不可达不得判 blocking；双 key 相同时 warn |
| `tests/test_deploy_migrate.py` / `test_env_merge.py`（改） | 8.1 的三类特殊迁移；幂等性 |
| `tests/test_embeddings.py`（改） | **R2 守卫**：embedding 永不读端点配置；`GATE=auto` 的解析 |

### 9.1 厂商中立守卫（`tests/test_openai_contract.py`）

「换一家就跑不通」如果只靠人工换厂商试，迟早会漏——真实厂商不进 CI，谁都不会每次改动都跑一遍。因此把它变成**可自动化的不变量**：

用一个 mock 端点模拟「**最小合规 OpenAI 服务**」——只接受 `model` / `messages` / `temperature` / `max_tokens`（流式加 `stream`，工具链路加 `tools` / `tool_choice`），**收到任何其它顶层字段就返回 400**。

断言：六个角色在 `KIND=online` 下的请求体全部通过该 mock。

这条测试的价值在于它**不需要任何真实厂商**，却能钉死 4.3 的规则 ①——将来有人再往主链路加一个厂商私有字段，CI 立刻红。配套再加两个 mock：

- 只认 `max_completion_tokens` 的端点 → 验证自适应切换后成功；
- 拒绝 `temperature` 的端点 → 验证省略后成功，且**不会**无限重试。

### 9.2 真机验证（单测覆盖不到）

| # | 项 | 说明 |
|---|---|---|
| 1 | 三个场景各跑一轮真实对话 + 一轮真实整合 | 比对输出质量；纯本地场景须与改造前逐项对齐 |
| 2 | **缓存命中率在重排 prompt 前后的实测对比** | R1 与 T0-1 的验收依据。用 `scripts/probe_consolidation.py`（已有，会报 prompt tokens）先打基线再对照 |
| 3 | **至少两家在线厂商 + 本地 LM Studio 跑同一套配置** | DeepSeek 为指定参考厂商；**第二家任选**（任何 OpenAI 兼容端点均可）。判据是「换厂商只改 `.env` 的 base_url/key/model，不改一行代码」——这是 Q1 那条硬要求的人工兜底，与 9.1 的自动守卫互补 |
| 4 | 插件链路（tools / 流式 / 图片）在在线端点下的兼容性 | **必须用未经修改的原版插件验证**：`data/plugins/` 是 gitignore 的，开发机副本可能被手工改过，兼容层缺口会因此漏到 release |
| 5 | 廉价模型的 JSON 遵循度 | 见 §11 Q3。`TEMPERATURE=0.3` 是为本地 E4B 标定的，在线廉价模型需重新标定 |
| 6 | **GUI「留空即继承」路径** | `stella-installer/` 下没有 JS 测试框架，P0-1 的前端半边只能人工验证：在 GUI 里把 8 个继承键留空并保存，确认 `.env` 里**没有**这 8 行（而不是写成 `KEY=`）；再填上值保存，确认写入且覆盖生效 |

---

## 10. 分期落地

| 期 | 内容 | 交付判据 |
|---|---|---|
| **P0** ✅ 已交付<br>（2026-08-28） | 修四个阻塞缺陷（`_env_inherit` + schema 废弃判定 + 三个 prompt 重排 + 截断不推进 checkpoint）；补 `session_compact` 的 api_key | 纯本地行为不变；阶段2 提取恢复工作（当前是坏的）；缓存前缀长度达标 → 落地情况与偏差见 §10.1 |
| **P1** 🟡 代码完成<br>（2026-08-28，离线验证跑过一轮、修完待复跑；厂商实测未做） | 端点×角色配置模型 + `core/llm/registry.py` + 六处构造点改造 + 闸门改并发度 + 参数兼容层 | 三个场景可通过手改 `.env` 跑通；纯本地逐字等价今天；**§9.1 契约测试进 CI 并通过**；DeepSeek + 第二家厂商各跑通一轮（只改 `.env`） → 落地情况、偏差、首轮 5 处缺陷与**仍欠的判据**见 §10.2 |
| **P2** | GUI「模型服务」分区（端点卡片 + 角色矩阵 + 三个预设 + 测试连接）；doctor 新检查项；迁移逻辑 | 全程 GUI 完成本地↔在线切换，存量 `.env` 自动迁移 |
| **P3** | 成本控制：Tier 0 剩余项 + Tier 1 预筛 + Tier 2 记账/预算 + 用量面板 + 降级链 | 缓存命中率与用量可见；日预算生效；超额只停记忆域 |

P0 可独立发布（它修的是现存 bug）。P1 之后功能已可用，P2 让它好用，P3 让它省钱。

### 10.1 P0 落地记录（2026-08-28）

| 项 | 状态 | 与原计划的差异 |
|---|---|---|
| P0-1 `_env_inherit` | ✅ | 无。settings + env_schema + config.html 三处协同，8 个继承键全部生效 |
| P0-2 废弃判定 | ✅ | 取推荐方案（查 `env_keys` 登记表）。顺带救回第二个误伤键 `MEMORY_COMPRESS_LOG_PATH` |
| P0-3 prompt 重排 | ✅ | 整合 ≈2094 / 提取 ≈1538 估算 token 可缓存；**会话压缩 ≈331 token 不达门槛**，且共用 key 也救不了，理由见 P0-3「已落地」小节 |
| P0-4 截断不推进 checkpoint | ✅ | 「重试一次」改为最多 3 档批量阶梯 + `OutputTruncatedError`；`finish_reason` 走 `generate_detailed()` 的返回值。usage 上报**未**一起做，留 P1 |
| §2 P1 清单：`session_compact` api_key | ✅ | 无 |

**交付判据对照**

- *纯本地行为不变*：全量 `pytest tests -q` → 1130 passed / 3 skipped（补测试前是 1103）；`ruff check .` 全绿；pyright 对四个改动模块 0 error。
- *阶段2 提取恢复工作*：`.env` 里三个空值键现已解析到父端点，`LMStudioBackend(base_url="")` 那条 `UnsupportedProtocol` 路径消失。
- *缓存前缀长度达标*：整合与提取达标；**压缩不达标，且不在 P0 解决**。

**遗留项（不阻塞 P1）**

1. `config.html` 的「留空即继承」路径**没有自动化守卫**——`stella-installer/` 下没有 JS 测试框架，本次只做了代码走读。已登记为 §9.2 第 6 项人工验证。
2. `scripts/probe_consolidation.py --positive` **尚未跑**。`memory/consolidation_prompt.py` 自己的注释规定「修改本模板前必须先跑」，本次改了模板（纯重排），需在有 LM Studio 的机器上补跑，确认防编造条款与正例提取能力没有回归。
3. `pyrightconfig.json` 仍指向不存在的 `.venv`（本机走 conda 环境）。与本方案无关的既有环境问题，未改。

### 10.2 P1 落地记录（2026-08-28）

**状态：代码完成；离线验证（ruff + pytest）已由用户代跑一轮，5 处缺陷已修，待复跑确认；真实厂商实测仍未做。** 本轮开发机的 shell 执行被环境拦住（只读命令可用，任何执行代码的命令一律拒绝），所以 `ruff` / `pytest` 不是我跑的——是用户在网络中断期间代跑的，日志见 `design_docs/bug_report/bug_report_2026_8_28#1.md`。这件事本身值得记一笔：**「代码走读通过」和「跑绿」之间那 5 处缺陷，靠走读一个都没抓到**。判据对照一节逐条写明了哪些是「已验证」、哪些还欠着。

| 项 | 状态 | 与原计划的差异 |
|---|---|---|
| P1-1 端点×角色配置模型 | ✅ 代码完成 | 4 个端点槽（`LOCAL` / `ONLINE_CHAT` / `ONLINE_MEMORY` / `EXTRA`）× 6 个角色（`CHAT` / `ROUTER` / `PLUGIN` / `COMPACT` / `CONSOLIDATION` / `EXTRACT`）**全部静态声明**。槽位数写死是硬约束，不是保守：`deploy/env_schema.py` 用 AST 扫 `config/settings.py` 里的字面量 `_env*("KEY", ...)` 调用，动态命名的端点永远不会出现在 GUI 上 |
| P1-2 `core/llm/registry.py` | ✅ 代码完成 | 无。解析一次并缓存；`reset_state()` 清缓存；`validate()` 只返回 `error` / `warn` 两级 |
| P1-3 六处构造点 | ✅ 代码完成 | 无。`ai_gateway` / `session_compact` / `router/fallback` / `consolidator`×2 / `astrbot_compat/llm/provider` 全部改成 `backend_for(ROLE_*)` |
| P1-4 闸门改并发度 | ✅ 代码完成 | 见偏差 ①。资源单位从「两把命名锁」变成「每个端点槽一个 `Semaphore(concurrency)`」；「绝不同时持有两把闸门」的铁律不变 |
| P1-5 参数兼容层 | ✅ 代码完成 | 无。`core/llm/compat.py` 按错误体关键词自适应 + 记住结果，每请求最多**一次**自适应重试且**不占**原有 3 次尝试预算 |
| P0-4 遗留的 usage 上报 | ✅ 代码完成 | 见偏差 ⑤。新增 `core/llm/usage_sink.py`，P1 只做上报口子，落库在 P3 |
| §9.1 契约测试 | ⚠️ 已跑一轮，修完待复跑 | 4 个新文件，见下「新增测试」与「验证记录」 |

**新增测试（4 个文件，共 +160 用例）**

| 文件 | 守什么 |
|---|---|
| `tests/test_openai_contract.py` | §9.1 契约：最小合规请求体、一次自适应重试、`tools` 透传、不依赖 `response_format` |
| `tests/test_llm_compat.py` | 差异自适应只按**措辞关键词**命中，不含任何厂商名——退化成厂商白名单就会被这组用例抓住 |
| `tests/test_scheduler_concurrency.py` | 并发度 1 与改造前的 `asyncio.Lock` 逐字等价；`LOCAL` 与 `EXTRA` 真正并行；解析不出来一律退回 1 |
| `tests/test_llm_registry.py` | 纯本地闸门拓扑等价、每条 `validate()` 分支、R1 同 key 告警、fallback 冷却、`embedding_gate()` 四态、**「日志与 `describe()` 里绝不出现 key 的值」** |

**与原计划的偏差**

① **§4.1 闸门命名**：方案写的资源名是 `chat` / `consolidation`（按用途命名），落地改为**按端点槽命名**（`LOCAL` / `ONLINE_CHAT` / `ONLINE_MEMORY` / `EXTRA`）。理由：闸门的物理意义是「此刻最多几个请求打到同一个端点上」，而端点才是那个被保护的资源；按用途命名在「两个角色绑同一个端点」时会立刻分裂成两把闸门，把本地那块显存放开成并发 2。`scheduler.RESOURCE_CHAT` / `RESOURCE_CONSOLIDATION` 保留为别名并注明「新代码不要用」。

② **§8.1 的 `LLM_TIMEOUT` 行**：方案原写端点 `TIMEOUT` 继承 `LLM_TIMEOUT`。落地**不继承**：`LLM_TIMEOUT`（=90.0）是**每轮管线预算**，而端点超时是单次 HTTP 请求的上限，两者语义不同且前者更短——继承会让在线整合（20~60 秒起）无谓超时。端点 `TIMEOUT` 默认写成字面量 `120.0`，与 `LMStudioBackend` 今天的默认值一致。

③ **`LLM_ROLE_COMPACT_MAX_TOKENS` 的 0 = 派生**：会话压缩的输出上限本就该跟着摘要字数上限走，多一个要手动对齐的键就是多一个会不一致的地方。落地取 `SESSION_SUMMARY_MAX_TOKENS × 3`（300 → 900），并保证派生结果永不为 0；显式填非 0 值时以显式值为准。其余 5 个角色的 `MAX_TOKENS` 填 0 仍是**错误**（回退 1024 并报 error）——只有 COMPACT 这一个键的 0 有特殊含义。

④ **新增 `_env_int_inherit` / `_env_float_inherit`**：P0 只做了字符串版的 `_env_inherit`。角色的 `TEMPERATURE`（float）与 `MAX_TOKENS`（int）也要「留空即继承它原来的那个旧键」（如 `LLM_ROLE_PLUGIN_TEMPERATURE` ← `ASTRBOT_LLM_TEMPERATURE`），否则 GUI 上留空会被读成 0——温度 0 与 max_tokens 0 都是有含义的合法值，靠 `_env_int` 分不出「留空」和「填 0」。端点的 `CONCURRENCY` / `TIMEOUT` **没有**用继承版：它们没有对应的旧键可继承，默认值就是字面量（并发度 1/4/2/1、超时 120.0）。

⑤ **新增 `core/llm/usage_sink.py`**：P0-4 明确把 usage 上报留给 P1。做成独立的 sink 模块（默认空实现）而不是直接写库：`core/llm` 不该 import `memory`，而 P3 的记账要落到 SQLite。P1 只保证 `usage` 被取出来并递给 sink。

⑥ **`LLMBackend.generate_detailed()` 给了非抽象默认实现**（转发 `generate()`，`finish_reason` 补空串）。它在 P0 是抽象方法，但那会让所有第三方/测试替身后端一升级就崩——项目里现存大量只实现 `generate()` 的替身。

⑦ **`MEMORY_EMBEDDING_GATE` 三态枚举替代布尔**：原 `LLM_SCHEDULER_GATE_EMBEDDING`（bool）在「embedding 与哪个槽共用闸门」这个问题上无法表达。新键取 `auto | <槽名> | none`，`auto` = 「与某个 `KIND=local` 且 `BASE_URL` 等于 `MEMORY_EMBEDDING_BASE_URL` 的槽共用闸门，找不到就不排队」。**兼容处理**：显式为假的旧布尔仍然表示「不排队」；显式写槽名时槽名优先。R2（embedding 恒本地）因此在配置层就是可检查的。

⑧ **纯本地等价靠「`EXTRA` 就是原来的 consolidation 闸门」实现**：`EXTRA` 的 `BASE_URL` 继承 `CONSOLIDATION_LM_STUDIO_BASE_URL`（与 `LOCAL` 同址）但**持有独立闸门**，且 `LLM_ROLE_CONSOLIDATION_ENDPOINT` 默认 `EXTRA`。改造后拓扑与今天逐字相同：CHAT/ROUTER/PLUGIN/COMPACT/EXTRACT → `LOCAL`（27B/GPU，串行），CONSOLIDATION → `EXTRA`（E4B/CPU，串行），embedding `auto` → `LOCAL`。只是改了名字。

⑨ **`scheduler.set_concurrency_resolver(fn)` 间接注入**：避开 `scheduler → registry → settings` 的导入环。代价是「谁来装解析器」变成了隐式的（`core.llm.registry` 模块底部的一行 import 副作用）——删掉它不会报任何错，只会让所有闸门静默退成并发 1。`tests/test_scheduler_concurrency.py::test_registry_installs_the_resolver_on_import` 是那行代码的唯一守卫。

⑩ **`astrbot_compat/llm/provider.py::get_current_key()` 仍返回 legacy `ASTRBOT_LLM_API_KEY`，不返回 `PLUGIN` 端点的 key**（安全决策，不是漏改）。这个函数是给第三方插件代码调的；把付费在线 key 递给它等于把 key 交给未审计的第三方代码。函数上方已就此写了注释。

⑪ **§4.3 ② 的关键词匹配前多了一步「反转义」**（`core/llm/compat.py::_searchable`）。方案只说「按错误体关键词匹配」，落地发现这一句在中文厂商上直接不成立：不少后端用 `ensure_ascii=True` 序列化 JSON，中文错误信息到线上是一串 `\uXXXX`，中文关键词一条都命中不了。做法是**追加**一份反转义副本（原文保留，反转义失败就只用原文），于是 ASCII 与中文两条路都通。这不是白名单——反转义是纯编码层动作，与是哪一家无关。若少了这一步，D5 的「换了也要跑得通」在中文厂商（含测试厂商 DeepSeek）上是假的。

**验证记录（用户于 2026-08-28 代跑 `ruff check` + `pytest tests -q`）**

首轮结果：`ruff` 3 errors，`pytest` **2 failed, 1290 passed, 3 skipped**（P0 基线 1130 passed / 3 skipped，+160 来自新增 4 个文件）。5 处缺陷逐条：

| # | 报告项 | 真因 | 修法 |
|---|---|---|---|
| 1 | `SIM105` `core/llm/openai_client.py:214` | `_record()` 里用了 `try/except/pass` | 改 `contextlib.suppress(KeyError, IndexError, TypeError)`，并把「上报是旁路，绝不能把请求本身弄失败」写进注释 |
| 2 | `I001` `tests/test_openai_contract.py:23` | 单行 import 超长未拆 | 拆成括号多行 |
| 3 | `F841` `tests/test_openai_contract.py:383` | `ep = _install(...)` 未使用 | 去掉赋值（同文件另一处的 `ep` 后面真的用到，保留） |
| 4 | `test_env_schema.py::test_schema_marks_inherited_defaults` | P1 新增 16 对继承项，没同步这个**手写基线**（用例自己的报错信息就写着「新增继承项请同步本用例」） | `expected` 补齐到 24 对，按「P1 前 / 端点槽 / 角色」分三组注释 |
| 5 | `test_llm_compat.py::test_learns_to_omit_temperature[中文用例]` | **不是实现缺陷，是用例的 helper 有问题**：`_TEMPERATURE_UNSUPPORTED_HINTS` 里本来就有「不支持」，但 `_body()` 用 `json.dumps` 默认的 `ensure_ascii=True` 把中文转成了 `\uXXXX`，关键词自然落空 | `_body()` 改 `ensure_ascii=False`（它模拟的本来就是原样返回 UTF-8 的后端）；**同时**给实现补 `_searchable()`（见偏差 ⑪）并新增 `test_learns_from_ascii_escaped_body` 守转义那条路——只改用例等于把一个真实厂商形状下的失效藏起来 |

顺手收的一项：`tests/test_env_inherit.py` 的 `INHERIT_PAIRS` 原是手抄的 8 对，而它的注释写着「全部继承型配置项」——P1 之后这句话是假的。改成**从 `build_schema()` 现算**，新增继承项自动进参数化，并加 `test_inherit_pairs_were_actually_discovered` 兜住「派生参数化塌成空集就静默不跑了」这个自毁风险。手写基线只留 `test_env_schema.py` 一份，两处分工：那边守「关系有没有被改错」，这边守「关系在运行时真解析出了值」。

**交付判据对照**

| 判据 | 状态 |
|---|---|
| 三个场景可通过手改 `.env` 跑通 | ❌ **未验证**（需要真实在线 key） |
| 纯本地逐字等价今天 | ⚠️ **代码走读 + 用例已跑**。拓扑等价的论证见偏差 ⑧，用例见 `test_llm_registry.py` 的「纯本地拓扑」组与 `test_scheduler_concurrency.py`，这两组在 2026-08-28 那轮里是绿的。**但「等价」的最终判据是真机对比，不是用例** |
| §9.1 契约测试进 CI 并通过 | ⚠️ **已跑一轮，修完待复跑**。文件落在 `tests/` 下即自动进 CI（`testpaths=["tests"]`）；首轮 2 failed 已修，期望复跑为 **1293 passed / 3 skipped**（1290 + 修好的 2 + 新增的 `test_learns_from_ascii_escaped_body`；`test_inherit_pairs_were_actually_discovered` 与 `test_env_inherit` 参数化的 +16 条会再往上加，具体数以复跑为准） |
| DeepSeek + 第二家厂商各跑通一轮 | ❌ **未验证**（需要真实 key，且必须在两家上各跑一轮才算 D5 的「换了也跑得通」成立） |

**遗留项（阻塞 P1 收尾，不阻塞 P2 开工）**

1. **复跑确认**：`ruff check .` 应为 0 error；`pytest tests -q` 应无 failed。首轮（2026-08-28）是 3 error / 2 failed，5 处缺陷已按上表修完，但**修完之后没人再跑过**——这一条不勾掉，P1 不算收口。
2. **两家厂商实测**未做，见上表。这是 D5 硬要求「不能出现换了就跑不通」的唯一验证手段。
3. **文档键表更新推迟到 P2**（与 `env_keys.RENAMED` 一起改，避免改两遍）：`docs/configuration.md:242,246,801`、`docs/capability-system.md:239`、`.env.example:104`。
4. P0 遗留的三项（`config.html` 继承路径人工验证、`probe_consolidation.py --positive`、`pyrightconfig.json` 指向不存在的 `.venv`）**仍未消**。

---

## 11. 决策记录、待实测项与风险

### 11.1 已定

| # | 项 | 结论 |
|---|---|---|
| Q1 | 目标厂商 | **按通用 OpenAI 规范设计，不绑定任何厂商。** 验收参考厂商为 DeepSeek，但它只是"第一个被试的"，不是"被适配的"——**硬要求：换一家厂商不得出现跑不通，且不得为此改代码，只允许改 `.env`**。落地见 §4.3 的三条规则（最小合规请求体 / 错误自适应而非厂商白名单 / 不依赖结构化输出能力），自动守卫见 §9.1，人工兜底见 §9.2 第 3 项 |

### 11.2 待实测阶段回答

以下五项**无法在纸面上定**，需要 P1/P3 跑起来后用真实数据回答。此处记录问题、判据与回答它所需的手段，避免实施时忘记。

| # | 项 | 何时能答 / 用什么答 |
|---|---|---|
| Q2 | 端点槽 4 个够不够 | P2 GUI 落地后看实际配置形态。静态 schema 约束下的取舍见 §3.2；若确实需要任意分角色 URL，补每角色的 `BASE_URL`/`API_KEY` 覆盖键（+12 键），**属于加法，不推翻现有结构** |
| Q3 | 阶段1 用廉价在线模型的 JSON 遵循度 | P1 真机验证。`CONSOLIDATION_LM_STUDIO_TEMPERATURE=0.3` 是为本地 E4B 标定的，需按所选模型重新标定。若遵循度不足：先降温度、再收紧 schema，**最后**才考虑打开 `response_format` 端点开关——但按 §4.3 规则 ③，正确性始终不得押在它上面 |
| Q4 | T1-1/T1-2 来源门控的漏整合代价 | P3。`settings.py:347` 的实测结论支持这个取舍，但阈值需用 `memory/benchmark/` 标定；同时验证"连续跳过上限"兜底确实能防止某群无限滞留 |
| Q5 | force 路径加大批量后的 @ 响应延迟 | P3。T0-5 会延后 @ 触发的响应，可接受上限需真机体感，不宜纸上定 |
| Q6 | 在线端点并发度默认值 4 是否合适 | P1。取决于厂商限流档位与实际群活跃度；`scheduler.snapshot()` 已能导出排队深度/等待时长，用它调而不是拍脑袋 |

### 11.3 风险

| # | 风险 | 应对 |
|---|---|---|
| R1 | 缓存命中依赖厂商实现 | 若厂商的前缀缓存粒度/TTL 与 §5.2 的假设不符，T0-1 的收益会低于预期。**因此 §6.2 的命中率面板不是可选项**——没有度量就无法判断优化是否生效，也无法判断 R1 双 key 是否真的起了作用 |
| R2 | 在线整合的隐私面 | 群聊原文会离开本机。这是在线化的固有代价，须在 GUI 端点卡片上明示，让用户知情后再选。场景 C（整合留本地）应作为有本地算力用户的推荐档显式呈现 |
| R3 | 厂商中立会随时间腐化 | 加字段是最容易的事，删字段最难。§9.1 的契约测试就是为此存在——它不需要真实厂商即可在 CI 里钉死这条约束 |
