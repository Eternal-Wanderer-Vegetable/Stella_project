# WP06 实施记录：消息、媒体及统一发送

- 日期：2026-10-21（Asia/Shanghai）
- 工作分支：`codex/cross-platform-implementation`
- 基线：WP05 状态提交 `69ac970`
- 实现提交：`d2270d1`（`feat(transport): add unified outbound delivery (WP06)`）
- 状态：WP06 本地实现及定向验收完成；XPLAT-IMPL 整体仍 **NOT READY**。

## 范围和结果

`core/transport/` 新增 `OutboundMessage`/`OutboundSegment`、版本化 `DeliveryTarget`、`MediaSource`、`AdapterCapabilities` 和 `OutboundService`。目标只能由可信 `BotRef`/`SceneRef` 构造，持久化不含事件句柄或凭据；发送使用事件携带的 Bot 或注册表中完全匹配的连接，不选择随机在线账号。OneBot v11 codec 通过锁定的 UniMessage API 转换文本、图片、文件、@ 和引用段；native extension 仅允许同 adapter。未知/线程场景没有 OneBot 持久目标编码。

发送前复核 Bot、adapter、平台、场景、能力和有效期。实例能力只能收窄 adapter 能力；图片/文件缺少上传能力时可用 fallback 文本，缺 quote/@ 能力时移除对应可选段；文本按能力上限有序拆分。`DeliveryResult` 保留 accepted/partial/failed/unknown/unsupported/expired 状态、全部 opaque 平台 ID 与每个物理发送段结果。显式平台拒绝标失败；发送途中超时或无法判定是否产生副作用标 unknown，并停止，不自动重投。API 接受但无消息 ID 仍记录 accepted，不宣称已读。

群聊、私聊、Cometa ack、主动 @、主动群发和能力清单已改走统一出站服务；群/私聊目标来自当前已归一化可信事件，后台主动路径来自可信 ChatContext。发送回执继续进入既有 DeliveryPlan 一次性 claim 与 receipt 链路。social schema v5 新增 `platform_message_ids_json`；v4→v5 在事务中保留旧 `platform_message_id` 并包装成单元素列表，不转换数字或猜测新含义。按任一 opaque ID 查回执、BOT_SELF 引用锚点和效果归因现可消费完整列表。

三个入口/Cometa 测试桩从 mock matcher 的 `send()` 改为假的统一出站服务，断言可信目标、分段内容、显式 Bot 与确认回执；生产校验不因测试替身而绕过。

## GitNexus upstream impact

编辑前索引基于 WP05 状态提交 `69ac970`，GitNexus 固定版本 1.6.11。图是下界；索引记录 17 个超过 512KB 的文件、2,700 个入口候选预算裁剪、25 个深度截断流程、763 个 callee 丢弃、910 个跨语言属性边界，以及 32-callable 上限。回调和框架注册入口另以源码与测试补证。原始 risk 均照录，未使用 `riskSharedAxes` 抵消风险。

| 目标 | 编辑前 upstream impact | 处置 |
| --- | --- | --- |
| `deliver_lines` | HIGH；10 impacted / 6 direct / 3 processes / 2 modules | 保留签名、逐逻辑段 one-shot 发送与 plan guard；接收新的 DeliveryResult，不对 unknown 重投。 |
| `coerce_platform_message_id` | HIGH；10 / 1 / 3 / 3 | 保留兼容首 ID API，新增全 ID 提取；ID 统一字符串化，不要求十进制。 |
| `DeliveryReceipt` | MEDIUM；21 / 11 / 0 flows | 保留 singular primary 字段并加 `platform_message_ids`，旧消费者仍可读。 |
| `seal_delivery_plan` | CRITICAL；14 / 3 / 5 / 4 | 未改合同、签名和摘要格式；沿用现有封存/核验路径。 |
| `_append_and_persist` | HIGH；10 / 1 / 3 / 3 | 增加完整消息 ID 列表写入，维持现有 turn/part 唯一语义。 |
| `record_delivery` | CRITICAL；12 / 3 / 4 / 6 | SQL 列和值数一一对应；独立 social v5 additive migration，不覆盖旧回执。 |
| `deliveries_for_turn` | HIGH；8 / 3 / 1 / 3 | 返回列表并保留 singular ID；effects 与 bot-message attribution 消费所有 ID。 |
| `find_delivery_by_platform_id` | UNKNOWN / 0 图调用者 | `rg` 确认测试显式调用；保留其跨列表 opaque-ID 精确查询与作用域/歧义守卫。 |
| `ai_gateway.py` 发送闭包 | 文件级 HIGH/CRITICAL | 群、私聊与后台主动路径逐一核查；事件闭包用当前 event 的 normalized identity。 |

提交前 `.gitnexus/gn detect-changes --scope all --limit 1000`：21 files / 54 symbols / 7 affected processes / HIGH；`scope=compare --base-ref main`：264 files / 589 symbols / 76 processes / CRITICAL（含 WP00–WP05）。两条命令均返回完整摘要，未标 PARTIAL/truncated；比较风险包含前序工作包。

阶段报告与状态文档检查：scope all 为 7 files / 14 symbols / 0 processes / LOW；compare main 为 265 files / 591 symbols / 76 processes / CRITICAL。比较结果覆盖前序源码与计划状态，不代表本次文档单独具有 CRITICAL 代码风险。

## 验收证据

| 命令/范围 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/test_transport_outbound.py tests/test_social_delivery.py tests/test_social_migrations.py tests/test_ai_gateway_deterministic_reply.py tests/cometa/test_gateway_wiring.py tests/test_private_chat_ingress.py tests/test_transport_normalizers.py tests/capability/test_capability_hooks.py tests/test_vision.py tests/observability/test_message_flow_runtime.py -q` | 138 passed；1 个环境 warning：测试中没有安装 adapter。 |
| `.venv/bin/python -m ruff check core/transport core/social/delivery.py core/social/contracts.py memory/social_schema.py memory/social_store.py memory/reply_effect_service.py stella_project/plugins/bot_main/ai_gateway.py tests/test_transport_outbound.py tests/test_social_delivery.py tests/test_social_migrations.py tests/test_ai_gateway_deterministic_reply.py tests/test_private_chat_ingress.py tests/cometa/test_gateway_wiring.py` | All checks passed。 |
| `.venv/bin/python scripts/generate_message_flow.py` | 新归档 `message-flow.72cc70e6e149.json`：141 nodes、139 source-resolved、8,952 closure sites、11,689 reachable symbols。 |
| `.venv/bin/python scripts/generate_message_flow.py --check` | 通过；归档与当前源码一致。 |
| `git diff --cached --check` | 实现提交前通过。 |
| GitNexus `detect-changes` | scope all：21 files / 54 symbols / 7 processes / HIGH；compare main：264 files / 589 symbols / 76 processes / CRITICAL。 |

社会 schema 迁移回归覆盖旧 v4 primary ID 回填；传输回归覆盖媒体/引用/附件段转换、opaque 和带前导零 ID、Bot 绑定、能力缩窄、长度拆分以及中途 unknown 停止。定向集包含既有 QQ 群/私聊、Cometa ack、能力图片和 message-flow runtime。未运行全量 Python suite。

## 数据边界与未完成验收

`STELLA_HOME` 未设置；所有数据库测试使用 pytest 临时目录。未读取、迁移或写入用户/生产库，未启动 Bot、真实模型或真实平台。OneBot codec 由当前锁定的 UniMessage/NoneBot API 和假发送验证；没有 OneBot live QQ 灰度，也没有代表性新平台 fixture/live、Windows native wheel、clean VM 或发布验收。线程/频道及未注册 adapter 仍 unsupported；整体继续 **NOT READY**。
