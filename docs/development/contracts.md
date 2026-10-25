# 当前分支合同与发布边界

中文 | [English](contracts.en.md) · [文档总览](../README.md)

<a id="610-的源码合同与发布门禁"></a>

2026-10-25 P04 将记忆源码合同推进至 schema 23/API 4，新增追加式传输消息事件、组件与关系表；社交旁表合同为 schema 5，Scheduling SQL 为 schema 2，Cometa Origin JSON 为 v3。已发布资产仍按各自构建合同校验，旧 native wheel 不得加载 schema 23 数据库。源码常量已对齐，但部署 wheel 尚未在本阶段验证。

| 来源 | 当前常量 |
| --- | --- |
| [Python schema](../../memory/schema.py) | SCHEMA_VERSION = 23 |
| [Python/native 合同](../../memory_rust/backend.py) | BACKEND_API_VERSION = 4; MEMORY_SCHEMA_VERSION = 23 |
| [Rust schema](../../memory_rust/native/src/schema.rs) | BACKEND_API_VERSION = 4; MEMORY_SCHEMA_VERSION = 23 |
| [Social schema](../../memory/social_schema.py) | SOCIAL_SCHEMA_VERSION = 5 |
| [Scheduling SQL schema](../../stella_project/plugins/bot_main/scheduling/migrations.py) | SCHEMA_VERSION = 2 |
| [Cometa Origin JSON](../../cometa/models.py) | schema_version = 3 |

这些常量只证明源码的兼容要求，不证明某份 wheel 已构建、加载或验收。切换分支时重新核对。

- 记忆 schema 23 / backend API 4：`memory/schema.py`、`memory_rust/backend.py` 与 `memory_rust/native/src/schema.rs` 必须一致。原生包版本不能替代导出常量校验。v23 追加 transport event/parts/relations，并保留旧整数 `msg_id` 供显式 QQ 兼容路径使用。
- Social schema 5：`social_deliveries.platform_message_ids_json` 保存一个物理发送片段的全部平台消息 ID；v4→v5 迁移只把既有首 ID 包装成单元素列表，不重新解释 ID。WP06 保留单 ID 兼容字段，同时支持不透明 ID 和逐段回执。
- Scheduling schema 2：task/run/audit/quota 记录保存可验证的 DeliveryTarget、主体与 scope；旧 QQ task 只有在 Bot/群目标明确可绑定时才迁移为可发送，其他行保持不可路由，旧配额放入隔离的 legacy scope。发送必须精确解析持久化 BotRef，unknown 不自动重试。
- P05 出站合同：`OutboundService.send` 按完整 Bot/scene/route 目标 FIFO 串行；每目标最多 32 个排队项，目标 lane 与配额状态各有 4096 项上限。`rate_limit_buckets` 独立同时执行 adapter、connection、scene、target 作用域与 `api`、`request` 类别；旧限流字段分别保留为 adapter API 桶与 connection API 桶，不把不同窗口压成一个限值。限流状态是进程内滑动窗口，进程重启后清零。每个物理片段及重试都占用配额；仅明确 FAILED、标准限流错误码且附带 retry-after 的请求可重试，默认最多 2 次，单次 retry-after 等待最多 30 秒，并仍受消息 deadline/窗口约束。UNKNOWN 永不重投；回执保存物理片段状态、尝试次数和不透明消息 ID。排队期间 Bot 绑定代际变化或断连会拒绝发送。同 self_id 可在不同 adapter 并存，同一 adapter 槽冲突仍拒绝。
- P06-T Telegram codec：锁定 `nonebot-adapter-telegram==0.1.0b20`，通过显式 `register_telegram_transport` 和 `TransportIngress` normalizer 映射 opt-in；没有默认 matcher/启动注册。来源为[锁定适配器源码](https://github.com/nonebot/adapter-telegram/tree/v0.1.0b20)及[Telegram Bot API](https://core.telegram.org/bots/api)。将 Bot/用户/Chat/topic/message ID 以不透明字符串保存在 Stella 合同中，发送时只接受 canonical 数字 Chat/topic ID，topic 必须与 chat 同目标；支持 private、group/supergroup 与 `message_thread_id`。reply 关系指向同 connection 与规范会话，尚未经过本地消息查询时标记 unresolved。入站媒体只保留类型/MIME/大小提示，不保存 Telegram file ID。发送使用精确 Bot 与 `send_to(chat_id, message_thread_id=...)` 回执；明确 `ActionFailed` 表示失败，网络错误/超时为 UNKNOWN 且不重投。默认 capability 只开放 private/group/topic、reply、image/file；user mention 和 channel post 不支持，proactive 仍关闭，未声明未经核验的速率额度；Python 字符数上限设为 2048，保守低于 Bot API 的 4096 UTF-16 code-unit 限额。Bot API 的 `message_id=0` 是不可用的 ephemeral ID，不能用于持久回复。当前 Bot API 使用独立的 `direct_messages_topic_id` 路由 direct-messages chat；锁定的 0.1.0b20 adapter 未暴露该字段，因此这类消息不认证/不路由。fixture pass 不等价于 Telegram live、关系/媒体 live 或权限验收；matrix 保持 `not_certified`，直到真实账号验收完成。
- P06-D Discord codec：锁定 `nonebot-adapter-discord==1.1.10`，由连接 owner 显式调用 `register_discord_transport` 并把 `DiscordNormalizer` 放入 `TransportIngress` 映射；不注册默认 matcher 或启动钩子。锁定适配器的消息事件只有 `channel_id` / `guild_id`，没有频道类型，因此 normalizer 要求调用方注入可信 `channel_resolver`，并核对解析结果中的频道、guild 与 parent ID；缺少元数据时拒绝。支持一对一 DM、guild text/announcement channel 与 announcement/public/private thread；group DM 不支持。Discord ID 在 Stella 合同中保留为字符串。thread 的 `scene_id` 与 `thread_id` 都是实际 thread channel ID，`parent_path` 保存 guild 与 parent channel；发送只用准确 `scene_id`，不会改投 parent。normalizer 校验 `direct_messages` / `guild_messages` intent；guild 内容还要求启用 `message_content`，或适配器明确标记 bot mention/reply。reply 只接受同一精确 channel 的 DEFAULT reference，目标消息未随事件提供时保持 unresolved；forward 与跨频道 reply 拒绝。编辑事件必须带 author、content 和平台 `edited_timestamp`。入站附件只保存类型/MIME/大小提示，不保存 URL 或 attachment ID。出口仅支持 text 与 reply，`allowed_mentions` 为空、Python 字符上限为 1900，reply 设 `fail_if_not_exists=true`；明确适配器 `ActionFailed`（含权限错误）是 FAILED，超时/其他网络结果是 UNKNOWN，均不自动重投。thread 发送权限由 Discord API 在精确目标上验证；线程需要 `SEND_MESSAGES_IN_THREADS`，夹具拒权不会转投 parent，但不代表 live 权限验收。主动发送、用户/角色 mention、媒体上传和 unrestricted passive capability 关闭；rate limit 与 send window 未认证。锁定 wheel 只安装在 `/tmp` 用于夹具，`.venv` 不变；无 live Bot/权限/driver 测试，matrix 保持 `not_certified`。
- Cometa Origin v3：BotRef 与 DeliveryTarget 同时保存并交叉校验；v1/v2 只按已知旧 OneBot QQ 语义兼容，无法证明目标身份的旧记录 fail closed。Cometa SQL 表结构保持 schema 1。
- 消息流程：`python scripts/generate_message_flow.py --check` 检查源码锚点、闭包与 manifest；源码变化后按生成器更新归档，不能把静态可达性当作实际执行。
- 前端：`pnpm --dir dashboard test`、`pnpm --dir dashboard build`；本地随包快照用 `pnpm --dir dashboard sync:webui` 同步。
- 隔离评估：`python scripts/run_flow_evaluation.py --mode isolated_pipeline --dataset <dataset_dir> --workdir <isolated_dir> --json`；还有 trace_playback / decision_recompute / model_validation 模式。workdir 与 dataset 必填，不能默认回落生产库。
- 归属重放：`python scripts/evaluate_dialogue_attribution.py --help` 查看冻结夹具、协议 prompt 与 `--guard`；离线重放不替代身份登记落库和真实 QQ 灰度。
- 发布版本：`pyproject.toml`、`cli/Cargo.toml`、`desktop/src-tauri/Cargo.toml`、Tauri 配置与对应 lockfile 同步。原生 wheel、launcher、runtime-manager 与私有 Dashboard 包保留独立组件版本。
- tag 发布依次构建面板、CPU backend 候选通道、离线负载、wheel、CLI 与四个安装器；每个 EXE 在 Windows runner 上验收后才进入发布 job。发布清单绑定大小/SHA-256，发布后回读校验。
- `VERSIONED_LAYOUT=0` 是当前工作流默认值；版本化 launcher 搬移路径尚未默认开启。hosted Windows 安装检查不是干净 VM/GUI 首启验收；完整 VM 矩阵见 `release_assets/VM-MATRIX.md`。

测试现状以目标提交 CI 为准；旧文档中的测试数字是有日期的快照。归属灰度与 Rust 排序差异见 [文档索引](../README.md)。
