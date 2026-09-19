# Stella 图片识别（视觉转述）实施计划 v1.0

> 状态：待实施（2026-09-19 定稿）
> 目标：让 @ Stella 的消息里携带图片时，Bot 能「看到」图并正常回复。

## 一、选定链路

```
QQ 消息（@Stella + 图）
    │
    ▼
group_silent_listener（priority 0）
    │  纯图片 → 落库为 "[图片]" 占位；图文 → 落库原文
    ▼
chat_handler（priority 3，@ 或回复 Bot 触发）
    │  extract_image_sources() → ctx.image_sources
    │  （含引用消息里的图；QQ CDN URL / 本地路径 / base64 都认）
    ▼
pre-hook describe_images（priority 60，build_context 之前）
    │  VISION 角色 → 视觉模型（本地或在线多模态，由配置决定）
    │  图 → 一句客观文字描述
    │  ctx.message += 「图片内容：xxx」
    │  group_messages 那行从 "[图片]" 改写为带描述的完整文本
    ▼
───────────────── 以下全部是旧有流程，零改动 ─────────────────
build_context（priority 50，尾巴里已是带描述的文本）
activate_capabilities（priority 45，Router 判定 + 记忆检索）
pipeline.run → _compose_prompt → LMStudioBackend.generate
（纯文本 prompt，尾部 = 用户原话 + 图片描述）
    ▼
post-hooks → 逐条发送
```

三条确认原则：

1. **转述由独立的 VISION 角色承担**——可绑任意端点槽（本地多模态、在线多模态均可），它只负责把图翻译成一句话；主对话模型全程收到纯文本。
2. **描述并进 `ctx.message`**——记忆检索、Router 判定、prompt 拼装、整合落库自动全部看到图片描述，不给每一环单独开口。
3. **QQ CDN URL 会过期**——所以描述必须在收到消息时生成并写进库；图片本身不留到以后再看。

**特性默认关闭（显式配置启用）**：本地消费级显卡部署的模型几乎不具备图像
转述能力，即使名义多模态也常无法正常工作。因此 `LLM_ROLE_VISION_ENDPOINT`
默认 `none`（未绑定），**所有新增行为（触发放行、占位落库、转述钩子）都以
`vision_available()` 为开关**：VISION 角色未绑定时，整条链路的行为与现版本
逐字节一致——纯图片 @ 不触发、被动图片不落库、图文 @ 只看文字。这不是
「降级路径」，而是默认状态；功能只在用户显式给 VISION 绑了可用端点后点亮。

## 二、现状：图片在哪几环被丢掉

| 环节 | 位置 | 现状 |
|---|---|---|
| 触发 | `ai_gateway.py:is_chat_trigger`（L413-423） | 要求 `is_tome()` + 非空 plaintext。`@Stella + 纯图` 被丢弃；`@Stella + 图文` 能触发但图被丢 |
| 落库 | `ai_gateway.py:record_group_chat`（L361-389） | `text = get_plaintext().strip()`，无文本即 return，纯图片消息不进记忆系统 |
| 上下文载体 | `core/context.py:ChatContext` | `message: str` 只有文本 |
| Pipeline | `core/pipeline.py`（L259） | `self._llm.generate(user_prompt, system_prompt)` 纯字符串 |
| LLM 后端 | `core/llm/lm_studio.py:_base_payload` | `content` 是字符串而非多模态 block 数组 |
| 被动摄入 | `record_group_chat` + `participation.observe` | 同样只看 plaintext，纯图片不参与评分与插话 |

**已有可复用能力**：

- `astrbot_compat/llm/entities.py:assemble_context()` 已会生成 `{"type":"image_url","image_url":{"url":...}}` block；`entities._to_image_data_url()` 处理 http(s) / `base64://` / `data:` / 本地路径四种来源。
- `core/llm/openai_client.py:chat_completion` 原样透传 messages 数组。
- OneBot 适配器 `_check_reply` 自动 `bot.get_msg` 填充 `event.reply.message`——引用消息的图片段可直接读，不需额外 API 调用。
- 角色 × 端点体系（`core/llm/registry.py`）天然支持再加一个角色：自动获得 describe / validate / log_summary / 用量归集 / 预算判定 / 闸门调度。
- `deploy/env_schema.py` 用 AST 扫 `config/settings.py` 的字面量 `_env*()` 生成 GUI——新键声明即出现在界面，端点槽位因此**固定为 4 个不可动态扩**。

## 三、方案选型

| 方案 | 结论 |
|---|---|
| **A. 视觉转述（VLM → 描述 → 走现有文本链路）** | ✅ **选定**。主链路改动最小，人格/记忆/回复闸门不变；VISION 未配置时优雅退化为 `[图片]` 占位；「本地文模 + 独立视觉端点」与「在线多模态做转述」都兼容 |
| B. 原生多模态（image block 直进主 CHAT 模型） | Phase 3 预留。要求 CHAT 模型本身是多模态，且要给 `LLMBackend.generate` 扩展签名；Phase 1 的 `ctx.image_sources` 抽象、hook 入口判断与落库均为它保留扩展位 |
| C. 转给插件管道 `request_llm(image_urls=)` | ❌。回复不带 Stella 人格与记忆，语义上属于插件而非 Stella 本人 |

**原生模式兼容说明（已复核）**：将来给 `LLMBackend` 补 `supports_images` + `generate_with_images` 时，只需要 Pipeline 的 LLM 调用点加一个分流；hook、提取、落库全不用动。两种模式下「把描述写进库」都值得做——转述模式它是模型看到的内容本身，原生模式它是记忆层的文本注脚。

## 四、改动清单

### 4.1 `config/settings.py`（GUI 自动出现）

新增「---------- 图片识别（视觉） ----------」小节：

```python
# 总开关（运行时停机位）。功能的真正启用条件是
# VISION_ENABLED=true 且 VISION 角色绑定了可用端点，见 vision_available()；
# 这个键只用于「临时关掉但保留端点配置」的场景。
VISION_ENABLED = _env_bool("VISION_ENABLED", "true")
# 单条消息最多处理几张图（QQ 九宫格刷屏保护）
VISION_MAX_IMAGES = _env_int("VISION_MAX_IMAGES", 3)
# 单张图片下载上限（字节）；本地路径/在线直传不受此限
VISION_MAX_IMAGE_BYTES = _env_int("VISION_MAX_IMAGE_BYTES", 8 * 1024 * 1024)
# 单张图片转述的超时（秒），超时该图占位、其余照常
VISION_DESCRIBE_TIMEOUT = _env_float("VISION_DESCRIBE_TIMEOUT", 60.0)
# 引用消息里的图片是否一并描述
VISION_INCLUDE_QUOTED = _env_bool("VISION_INCLUDE_QUOTED", "true")
```

角色段新增一组（与既有六角色同构）：

```python
# 图片转述。**默认 none = 未绑定 = 功能关闭**：本地消费级显卡部署的模型
# 几乎不具备图像转述能力，必须显式给本角色绑一个确认可用的视觉端点才启用。
# 未绑定时所有识图相关行为不生效（见 vision_available()），链路与旧版一致。
# 绑到本地槽时用多模态模型（如 qwen-vl）；绑到在线槽时注意——群聊图片会
# 以 URL 形式发往第三方服务。
LLM_ROLE_VISION_ENDPOINT = _env("LLM_ROLE_VISION_ENDPOINT", "none")
LLM_ROLE_VISION_MODEL = _env("LLM_ROLE_VISION_MODEL", "")
LLM_ROLE_VISION_TEMPERATURE = _env_float("LLM_ROLE_VISION_TEMPERATURE", 0.3)
LLM_ROLE_VISION_MAX_TOKENS = _env_int("LLM_ROLE_VISION_MAX_TOKENS", 300)
LLM_ROLE_VISION_FALLBACK_ENDPOINT = _env("LLM_ROLE_VISION_FALLBACK_ENDPOINT", "")
```

隐私注释：把 VISION 绑到在线端点时，群聊图片会发往第三方服务，需在注释里写明。

### 4.2 `core/llm/registry.py`

- `ROLE_VISION = "vision"`，加入 `ROLES` 与 `__all__`。
- 其余自动生效：`_binding_from_settings` / `describe` / `log_summary` / `backend_for` / `gate_of` / `budget_blocked` / `paused_roles`。

### 4.3 新模块 `core/vision.py`（约 200 行）

```python
def vision_available() -> bool
    # 「识图功能此刻是否可用」的单一判据，所有新增行为的开关：
    #   VISION_ENABLED and backend_for(ROLE_VISION) is not None
    # 未绑定时（默认）一律 False——触发、落库、钩子全部走旧路径。

def extract_image_sources(event, *, include_quoted: bool = True) -> list[str]
    # 扫 event.get_message() 的 image 段：data.url（QQ CDN）→ data.file → 本地 path
    # include_quoted 时再扫 event.reply.message（适配器已自动 get_msg）
    # 去重、按 VISION_MAX_IMAGES 截断
    # 返回统一形态：http(s) URL / "base64://" / "data:" / 本地路径

async def describe_images(sources: list[str], *, user_text: str = "") -> list[str]
    # sources 空 → []；vision_available()=False → []
    # budget_blocked(ROLE_VISION) → []（预算拦下时退化为占位，不发提示句）
    # 每张图独立 try：normalize → acquire(gate_of(ROLE_VISION)) →
    #   chat_completion([{text: 提示词}, {image_url: {url}}])
    # 单张 VISION_DESCRIBE_TIMEOUT；失败图占位、成功图得 caption
    # 进程内 LRU 缓存（key = 源字符串），同一 URL 重复出现不重复计费
    # normalize 复用 _to_image_data_url 的语义（http 直传 / base64:// / data: /
    #   本地路径读文件转 data URL，受 VISION_MAX_IMAGE_BYTES 限制）
    # caption 提示词写死一句中文（客观描述，1-2 句），不进配置
```

### 4.4 `core/context.py`

`ChatContext` 增加：

```python
image_sources: list[str] = field(default_factory=list)   # 接入层提取的图
image_captions: list[str] = field(default_factory=list)  # 转述钩子产出
```

### 4.5 `stella_project/plugins/bot_main/ai_gateway.py`（4 处，全部以 `vision_available()` 为开关）

**未绑定时（默认）这四处的行为与现版本逐字节一致**：纯图片 @ 不触发、
纯图片消息不落库、图文 @ 只看文字。

1. `record_group_chat`：`vision_available()` 且含 image 段时，text 落空记 `"[图片]"` 占位（图文则原文入库）。
2. `is_chat_trigger`：`vision_available()` 时放行条件放宽为 `is_tome() and (非空文本 or 有 image 段 or 引用里有图)`；`vision_available()` 为 False 时保持原判据逐字不变。`is_tome()` 已含「回复 Bot 消息」语义。
3. `handle_chat`：`vision_available()` 时 `ctx.image_sources = extract_image_sources(...)`（默认空列表）。
4. 注册新 pre-hook `describe_images_hook`，**priority=60**（先于 build_context=50 跑，保证尾巴组装时库里已是带 caption 的内容）：

```python
async def describe_images_hook(ctx: ChatContext) -> ChatContext:
    caps = await describe_images(ctx.image_sources, user_text=ctx.message)
    if caps:
        ctx.image_captions = caps
        ctx.message += f"「图片内容：{'；'.join(caps)}」"
        await update_recorded_message(ctx)  # 按 msg_id 回写刚落库那行
    return ctx
```

**为什么不是先转述再落库**：priority-0 落库是防「handler 崩溃丢消息」的保险（2026-08-17 缺陷的教训），必须保持先写。占位 → 改写之间的窗口里定时整合可能拿到 `[图片]` 占位，可接受。

### 4.6 `memory/pre_processors.py` + `memory/schema.py`

- `group_messages` 增加 `msg_id` 列（`ensure_v2_schema` 的 additive migration 惯例，`ALTER TABLE` 容错，老行留 NULL）。
- `record_message` 插入时带上 `ctx.msg_id`。
- 新增 `update_message_content(msg_id, content)`：按平台 msg_id 回写最终内容。

### 4.7 明确不改的部分

- `core/pipeline.py`、`core/llm/lm_studio.py`、`LLMBackend`：一行不动。
- `core/llm/usage_store.py`：VISION 属对话域（不进 `MEMORY_ROLES`），`pause_memory` 放行、`pause_all` 拦下，语义已正确。
- `deploy/env_schema.py` / `deploy/env_keys.py`：新键自动进 GUI，无需登记。
- AstrBot 插件管道：插件侧识图（`request_llm(image_urls=)`）已可用；PLUGIN 角色若要识图，绑到视觉端点即可。

## 五、降级与边界

| 场景 | 行为 |
|---|---|
| **VISION 角色未绑定（默认）** | **与现版本逐字节一致**：纯图片 @ 不触发、纯图片消息不落库、图文 @ 只看文字 |
| VISION 已绑定但 `VISION_ENABLED=false` | 同上，全部新行为关闭（临时停机位，不用改端点配置） |
| VLM 调用失败 / 超时 / HTTP 错误 | 该图占位（`[图片]`），其余图正常；hook 不抛异常 |
| 预算 `pause_all` 超额 | `budget_blocked` 拦下 → 占位回复，静默不发提示句 |
| 纯图片 @（无文字，VISION 可用） | `ctx.message = "[图片]"` + caption 追加，pipeline 正常走 |
| 被动纯图片消息（VISION 可用） | 入库为 `[图片]`；**不参与** participation 评分与主动插话（Phase 1 明确不做） |
| 引用消息含图 | `VISION_INCLUDE_QUOTED=true` 时一并描述 |
| GIF 表情 / 贴纸（mface） | OneBot 不保证可下载，Phase 1 不处理 |
| 在线视觉端点 | 图片出网——配置注释与文档明确标注隐私边界 |

## 六、分阶段

- **Phase 1（本次）**：被动识图 = 配置 + `core/vision.py` + gateway 4 处 + schema `msg_id` 列 + hook。约 1 个新文件、7 处改动。**默认关闭**：`LLM_ROLE_VISION_ENDPOINT=none` 时行为与现版本一致，显式绑定端点后点亮。
- **Phase 2（可选）**：被动图片转述（后台任务给 `group_messages` 补 caption，供主动插话与后续 @ 引用）；贴纸/表情包支持。
- **Phase 3（可选）**：CHAT 模型换多模态时，给 `LLMBackend` 加 `supports_images` + `generate_with_images`，Pipeline 调用点加分流；Phase 1 的 hook 入口已留好这个分支位。

## 七、测试计划

| 文件 | 覆盖点 |
|---|---|
| `tests/test_vision.py`（新） | `extract_image_sources`（image 段 / reply / mface 排除 / 截断）；`describe_images`（mock `chat_completion`：正常 / 超时 / 未绑定 / 预算拦下 / LRU 命中）；`vision_available()` 双条件 |
| 新增 gateway 测试 | `is_chat_trigger`：**VISION 未绑定时纯图片 @ 不触发（回归现版本行为）**、绑定时放行；`record_group_chat` 占位落库仅在 VISION 可用时生效 |
| `tests/test_llm_registry.py` | 修 `ROLES` 断言（L992），VISION 绑定解析 |
| `tests/test_pipeline_compose.py` | `ctx.message` 携带 caption 后的 prompt 拼装 |
| 手动验证 | `.env` 里 `LLM_ROLE_VISION_ENDPOINT` 显式绑到可用视觉端点（本地或在线）→ 群里 `@Stella 发图` 实测；未绑定时回归确认行为与旧版一致 |
