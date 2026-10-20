# 跨平台执行清单附录（2026-10-20）

基线 `ba582a922f4d3379b6397c4c0a8d8ef3e7c3e77d`；对应[执行方案](2026-10-20-gitnexus-cross-platform-plan.md)。本附录只登记计划；未执行平台接入。

## A. 全量运行入口映射

声明入口 50，注册扫描 34；双向差集为空。重复源码锚点可能代表不同语义入口，不能去重成较小分母。

| entry_id | 流程族 | 源码锚点 | 责任包 |
| --- | --- | --- | --- |
| `gateway.record_group_chat` | message | `stella_project/plugins/bot_main/ai_gateway.py#record_group_chat` | WP05/11 |
| `gateway.handle_chat` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_chat` | WP05/11 |
| `gateway.handle_private_chat` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_private_chat` | WP05/11 |
| `gateway.handle_command` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_chat` | WP05/11 |
| `webui.chat_ingress` | message | `webui/chat_ingress.py#run_turn` | WP05/11 |
| `gateway.group_silent_listener` | message | `stella_project/plugins/bot_main/ai_gateway.py#group_silent_listener` | WP05/11 |
| `gateway.plugin_handler` | message | `stella_project/plugins/bot_main/ai_gateway.py#plugin_handler` | WP05/08/11 |
| `gateway.chat_handler` | message | `stella_project/plugins/bot_main/ai_gateway.py#chat_handler` | WP05/11 |
| `gateway.private_chat_handler` | message | `stella_project/plugins/bot_main/ai_gateway.py#private_chat_handler` | WP05/11 |
| `gateway.addressing_handler` | message | `stella_project/plugins/bot_main/ai_gateway.py#addressing_handler` | WP05/11 |
| `gateway.toggle_handler` | message | `stella_project/plugins/bot_main/ai_gateway.py#toggle_handler` | WP05/11 |
| `gateway.capability_handler` | message | `stella_project/plugins/bot_main/ai_gateway.py#capability_handler` | WP05/11 |
| `gateway.reload_handler` | message | `stella_project/plugins/bot_main/ai_gateway.py#reload_handler` | WP05/11 |
| `gateway.scheduling_handler` | message | `stella_project/plugins/bot_main/ai_gateway.py#scheduling_handler` | WP05/11 |
| `gateway.proactive_speak_job` | proactive | `stella_project/plugins/bot_main/ai_gateway.py#proactive_speak_job` | WP07/04/11 |
| `gateway.proactive_at_user` | proactive | `stella_project/plugins/bot_main/ai_gateway.py#_proactive_at_user` | WP07/04/11 |
| `gateway.proactive_speak_for_group` | proactive | `stella_project/plugins/bot_main/ai_gateway.py#_proactive_speak_for_group` | WP07/04/11 |
| `consolidator.consolidate_group` | memory | `memory/consolidator.py#MemoryConsolidator.consolidate_group` | WP03/04/11 |
| `memory.process_new_candidates` | memory | `memory/memory_manager.py#MemoryManager.process_new_candidates` | WP03/04/11 |
| `compressor.run_weekly` | memory | `memory/compressor.py#MemoryCompressor.run_weekly` | WP03/04/11 |
| `social.run_due_jobs` | social | `memory/social_worker.py#run_due_jobs` | WP04/06/11 |
| `reply_effect.resolve` | social | `memory/reply_effect_service.py#resolve_effect` | WP04/06/11 |
| `session_compact.compact_once` | maintenance | `memory/session_compact.py#compact_once` | WP02/04/07/11 |
| `gateway.idle_maintenance` | maintenance | `stella_project/plugins/bot_main/ai_gateway.py#_proactive_speak_impl` | WP02/04/07/11 |
| `scheduling.tick_once` | scheduling | `stella_project/plugins/bot_main/scheduling/runtime.py#tick_once` | WP07/11 |
| `knowledge.ingest_content` | knowledge | `knowledge/ingest.py#ingest_content` | WP04/11 |
| `cometa.worker.tick` | cometa | `cometa/worker.py#CometaWorker._tick` | WP07/11 |
| `bot_main.start_scheduling` | lifecycle | `stella_project/plugins/bot_main/ai_gateway.py#_start_scheduling` | WP09/07/11 |
| `bot_main.start_cometa` | lifecycle | `stella_project/plugins/bot_main/ai_gateway.py#_start_cometa` | WP09/07/11 |
| `bot_main.start_stop_watcher` | lifecycle | `stella_project/plugins/bot_main/ai_gateway.py#_start_stop_watcher` | WP09/07/11 |
| `bot_main.start_capture_gate` | lifecycle | `stella_project/plugins/bot_main/ai_gateway.py#_start_capture_gate` | WP09/07/11 |
| `bot_main.start_hot_reload_watcher` | lifecycle | `stella_project/plugins/bot_main/ai_gateway.py#_start_hot_reload_watcher` | WP09/07/11 |
| `bot_main.graceful_shutdown` | lifecycle | `stella_project/plugins/bot_main/ai_gateway.py#_graceful_shutdown` | WP09/07/11 |
| `bot_main.flow_ingress` | message | `stella_project/plugins/bot_main/ai_gateway.py#_flow_ingress_root` | WP05/11 |
| `bot_main.flow_ingress_end` | message | `stella_project/plugins/bot_main/ai_gateway.py#_flow_ingress_end` | WP05/11 |
| `gateway.handle_plugin_fn` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_plugin` | WP05/08/11 |
| `gateway.handle_addressing_fn` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_addressing` | WP05/11 |
| `gateway.handle_toggle_fn` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_toggle` | WP05/11 |
| `gateway.handle_capability_query_fn` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_capability_query` | WP05/11 |
| `gateway.handle_reload_fn` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_reload` | WP05/11 |
| `gateway.handle_scheduling_fn` | message | `stella_project/plugins/bot_main/ai_gateway.py#handle_scheduling` | WP05/11 |
| `gateway.participation_tick_job` | proactive | `stella_project/plugins/bot_main/ai_gateway.py#participation_tick_job` | WP07/04/11 |
| `gateway.expression_sweep_job` | maintenance | `stella_project/plugins/bot_main/ai_gateway.py#expression_sweep_job` | WP02/04/07/11 |
| `gateway.session_idle_check_job` | maintenance | `stella_project/plugins/bot_main/ai_gateway.py#session_idle_check_job` | WP02/04/07/11 |
| `gateway.consolidation_drain_job` | memory | `stella_project/plugins/bot_main/ai_gateway.py#consolidation_drain_job` | WP03/04/11 |
| `gateway.trim_messages_job` | maintenance | `stella_project/plugins/bot_main/ai_gateway.py#trim_messages_job` | WP02/04/07/11 |
| `gateway.weekly_compress` | memory | `stella_project/plugins/bot_main/ai_gateway.py#weekly_compress` | WP03/04/11 |
| `social_worker.register_resolve_effect` | social | `memory/social_worker.py#resolve_effect` | WP04/06/11 |
| `nonebot.matcher_dispatch` | message | `stella_project/plugins/bot_main/ai_gateway.py#record_group_chat` | WP05/11 |
| `rust.promotion` | memory | `memory_rust/native/src/promotion.rs#promote` | WP03/04/11 |

## B. 适配器验收分母

官方注册快照 32 项；SHA-256 `6e9d36324a4a2f209a569cbb9c9bb7ab1b3696ae392446af807e7787f0e0119a`。来源：[adapters.json5](https://raw.githubusercontent.com/nonebot/nonebot2/master/assets/adapters.json5)。当前所有行均为 not_run；候选方案并非已认证结果。P0/P1/P2仅表示实施顺序。

| 平台/协议 | module_name | 包名 | 顺序 | 当前验收 |
| --- | --- | --- | --- | --- |
| OneBot V11 | `nonebot.adapters.onebot.v11` | `nonebot-adapter-onebot` | P0 | L0/L1/L2/live 未执行；L3逐能力确认 |
| 钉钉 | `nonebot.adapters.ding` | `nonebot-adapter-ding` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| 飞书 | `nonebot.adapters.feishu` | `nonebot-adapter-feishu` | P1 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Telegram | `nonebot.adapters.telegram` | `nonebot-adapter-telegram` | P1 | L0/L1/L2/live 未执行；L3逐能力确认 |
| QQ | `nonebot.adapters.qq` | `nonebot-adapter-qq` | P1 | L0/L1/L2/live 未执行；L3逐能力确认 |
| 开黑啦 | `nonebot.adapters.kaiheila` | `nonebot-adapter-kaiheila` | P1 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Mirai | `nonebot.adapters.mirai` | `nonebot-adapter-mirai` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| OneBot V12 | `nonebot.adapters.onebot.v12` | `nonebot-adapter-onebot` | P1 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Console | `nonebot.adapters.console` | `nonebot-adapter-console` | P1 | L0/L1/L2/live 未执行；L3逐能力确认 |
| GitHub | `nonebot.adapters.github` | `nonebot-adapter-github` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Ntchat | `nonebot.adapters.ntchat` | `nonebot-adapter-ntchat` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Minecraft | `nonebot.adapters.minecraft` | `nonebot-adapter-minecraft` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| BilibiliLive | `nonebot.adapters.bilibili` | `nonebot-adapter-bilibili` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Walle-Q | `nonebot_adapter_walleq` | `nonebot-adapter-walleq` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| 大别野 | `nonebot.adapters.villa` | `nonebot-adapter-villa` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| RedProtocol | `nonebot.adapters.red` | `nonebot-adapter-red` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Discord | `nonebot.adapters.discord` | `nonebot-adapter-discord` | P1 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Satori | `nonebot.adapters.satori` | `nonebot-adapter-satori` | P1 | L0/L1/L2/live 未执行；L3逐能力确认 |
| DoDo | `nonebot.adapters.dodo` | `nonebot-adapter-dodo` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| RocketChat | `nonebot.adapters.rocketchat` | `nonebot-adapter-rocketchat` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Kritor | `nonebot.adapters.kritor` | `nonebot-adapter-kritor` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Tailchat | `nonebot_adapter_tailchat` | `nonebot-adapter-tailchat` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Mail | `nonebot.adapters.mail` | `nonebot-adapter-mail` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| 黑盒语音 | `nonebot.adapters.heybox` | `nonebot-adapter-heybox` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| WXMP | `nonebot.adapters.wxmp` | `nonebot-adapter-wxmp` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| nonebot-adapter-milky | `nonebot.adapters.milky` | `nonebot-adapter-milky` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| nonebot-adapter-efchat | `nonebot.adapters.efchat` | `nonebot-adapter-efchat` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| nonebot-adapter-vocechat | `nonebot.adapters.vocechat` | `nonebot-adapter-vocechat` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| B站直播间 | `nonebot.adapters.bilibili_live` | `nonebot-adapter-bilibili-live` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| 云湖适配器 | `nonebot.adapters.yunhu` | `nonebot-adapter-yunhu` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| WxClaw | `nonebot.adapters.wxclaw` | `nonebot-adapter-wxclaw` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |
| Matrix | `nonebot.adapters.matrix` | `nonebot-adapter-matrix` | P2 | L0/L1/L2/live 未执行；L3逐能力确认 |

## C. 生产/部署文件审查全集

字面量命中 123 文件、1112 行；与图中传递依赖、分析目标和运行入口锚点合并后 180 个候选文件。下表每行给出责任归属；图命中含导入/文档传播噪声，条目是审查清单，非强制修改清单。完整行号与片段见 [literal-coupling-inventory.json](../reports/evidence/cross-platform-20261020/literal-coupling-inventory.json)。

| 文件 | 字面量行数 | 图/入口证据 | 责任包 | 处置 |
| --- | ---: | --- | --- | --- |
| `.env.example` | 9 | — | WP09 | 装配/配置/健康 |
| `Dockerfile` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `astrbot_compat/base.py` | 0 | 是 | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/components.py` | 56 | — | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/context.py` | 10 | 是 | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/events.py` | 16 | 是 | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/filters.py` | 3 | — | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/llm/__init__.py` | 8 | — | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/llm/agent.py` | 5 | — | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/llm/entities.py` | 4 | — | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/llm/message.py` | 8 | — | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/pipeline.py` | 0 | 是 | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/render.py` | 1 | — | WP08 | 插件兼容/工具事件 |
| `astrbot_compat/shim.py` | 6 | — | WP08 | 插件兼容/工具事件 |
| `bot.py` | 3 | 是 | WP09 | 装配/配置/健康 |
| `capability/adapters/knowledge.py` | 0 | 是 | WP02/04 | 共享消费者复核，按真实调用归属 |
| `capability/delegation.py` | 0 | 是 | WP02/04 | 共享消费者复核，按真实调用归属 |
| `capability/hooks.py` | 0 | 是 | WP08 | 插件兼容/工具事件 |
| `capability/providers/knowledge.py` | 1 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `cli/src/status.rs` | 4 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `cometa/artifacts.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/backends/base.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/backends/codex.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/backends/codex_auth.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/backends/codex_events.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/backends/fake.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/backends/registry.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/config.py` | 3 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/delivery.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/executor.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/migrations.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/models.py` | 1 | — | WP07 | 后台/任务/持久目标 |
| `cometa/policy.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/presentation.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/runtime.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/service.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/store.py` | 6 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/supervisor.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/worker.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `cometa/workspace.py` | 0 | 是 | WP07 | 后台/任务/持久目标 |
| `config/settings.py` | 7 | — | WP02/04 | 共享消费者复核，按真实调用归属 |
| `config/space_map.py` | 6 | — | WP01 | 身份/注册/空间 |
| `config/spaces.py` | 9 | 是 | WP01 | 身份/注册/空间 |
| `core/context.py` | 9 | 是 | WP02 | 上下文/身份信封 |
| `core/conversation.py` | 19 | 是 | WP01 | 身份/注册/空间 |
| `core/dialogue_attribution.py` | 0 | 目标/入口 | WP02 | 回复协议/SourceEvidence/可信用户标签 |
| `core/evaluation/dataset.py` | 1 | — | WP02/04 | 共享消费者复核，按真实调用归属 |
| `core/evaluation/runner.py` | 5 | — | WP02/04 | 共享消费者复核，按真实调用归属 |
| `core/observability/flows/message-flow.dcb0696583be.json` | 156 | — | WP11 | 重生成/观测合同 |
| `core/pipeline.py` | 0 | 是 | WP02/04 | 共享消费者复核，按真实调用归属 |
| `core/planner.py` | 0 | 是 | WP02/04 | 共享消费者复核，按真实调用归属 |
| `core/reply_gate.py` | 3 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `core/runtime/facade.py` | 0 | 是 | WP02 | 上下文/身份信封 |
| `core/runtime/turn_service.py` | 0 | 是 | WP02 | 上下文/身份信封 |
| `core/social/contracts.py` | 2 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `core/social/delivery.py` | 4 | 是 | WP06 | 投递/媒体；vision与WP05联动 |
| `core/turn_runtime.py` | 5 | — | WP02/04 | 共享消费者复核，按真实调用归属 |
| `core/vision.py` | 2 | — | WP06 | 投递/媒体；vision与WP05联动 |
| `dashboard/src/views/BackendOfflinePage.vue` | 6 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `dashboard/src/views/GroupsPage.vue` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `dashboard/src/views/PersonaPage.vue` | 4 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `dashboard/src/views/PlatformsPage.vue` | 5 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `dashboard/src/views/SettingsPage.vue` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `dashboard/src/views/data/PersonalMemoryPage.vue` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `dashboard/tests/flow-store.spec.ts` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/__main__.py` | 8 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/acquire.py` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/bootstrap.py` | 4 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/checks.py` | 18 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/env_keys.py` | 11 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/init_wizard.py` | 18 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/migrate.py` | 2 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/models.py` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/napcat.py` | 38 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/nsis_bootstrap_helper.py` | 4 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `deploy/probe.py` | 9 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `desktop/src-tauri/installer-hooks.nsh` | 3 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `desktop/src-tauri/src/commands.rs` | 31 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `docker-compose.yml` | 15 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `entrypoint.sh` | 3 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `extensions/__init__.py` | 0 | 是 | WP09 | 装配/配置/健康 |
| `extensions/link_monitor/__init__.py` | 11 | 是 | WP09 | 装配/配置/健康 |
| `knowledge/acl.py` | 0 | 目标/入口 | WP04 | KB主体、owner/grants及权限谓词 |
| `knowledge/embedding.py` | 0 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `knowledge/ingest.py` | 0 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `knowledge/retrieval.py` | 0 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `knowledge/service.py` | 0 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `knowledge/store.py` | 0 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/benchmark.py` | 4 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/compressor.py` | 0 | 目标/入口 | WP04/07 | 记忆压缩入口及身份/空间作用域 |
| `memory/consolidator.py` | 35 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/conversation_identity.py` | 0 | 是 | WP02 | 上下文/身份信封 |
| `memory/conversation_projection.py` | 0 | 目标/入口 | WP02 | 不透明消息ID/旧QQcodec/转录格式 |
| `memory/conversation_registry.py` | 8 | 是 | WP01 | 身份/注册/空间 |
| `memory/db_cleaner.py` | 2 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/evidence_contract.py` | 6 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/expression_learning.py` | 8 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/expression_store.py` | 5 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/memory_manager.py` | 2 | 是 | WP03 | 双后端/数据迁移 |
| `memory/migrations.py` | 12 | — | WP03 | 双后端/数据迁移 |
| `memory/ownership.py` | 3 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/participation/__init__.py` | 9 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/participation/buffer.py` | 1 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/participation/decision.py` | 5 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/participation/observability.py` | 1 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/participation/state.py` | 1 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/personal_sharing.py` | 1 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/post_processors.py` | 0 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/pre_processors.py` | 7 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/proactive.py` | 31 | — | WP07 | 后台/任务/持久目标 |
| `memory/proactive_contract.py` | 5 | 是 | WP07 | 后台/任务/持久目标 |
| `memory/proactive_gate.py` | 6 | — | WP07 | 后台/任务/持久目标 |
| `memory/proactive_state.py` | 9 | — | WP07 | 后台/任务/持久目标 |
| `memory/proactive_target.py` | 10 | 是 | WP07 | 后台/任务/持久目标 |
| `memory/reply_effect_service.py` | 2 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/retrieval_v2.py` | 6 | 是 | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/retriever.py` | 4 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/session_compact.py` | 10 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/session_context.py` | 20 | — | WP07 | 后台/任务/持久目标 |
| `memory/social_schema.py` | 6 | — | WP04 | 记忆/权限/主体；存储入口与WP03联动 |
| `memory/social_worker.py` | 0 | 目标/入口 | WP04/07 | 社会证据与后台任务主体作用域 |
| `memory_rust/__init__.py` | 0 | 是 | WP03 | 双后端/数据迁移 |
| `memory_rust/backend.py` | 3 | — | WP03 | 双后端/数据迁移 |
| `memory_rust/benchmark.py` | 2 | 是 | WP03 | 双后端/数据迁移 |
| `memory_rust/native/src/lib.rs` | 0 | 是 | WP03 | 双后端/数据迁移 |
| `memory_rust/native/src/promotion.rs` | 7 | 是 | WP03 | 双后端/数据迁移 |
| `memory_rust/native/src/retrieval.rs` | 6 | 是 | WP03 | 双后端/数据迁移 |
| `memory_rust/python_backend.py` | 0 | 是 | WP03 | 双后端/数据迁移 |
| `memory_rust/selector.py` | 0 | 是 | WP03 | 双后端/数据迁移 |
| `pyproject.toml` | 4 | — | WP09 | 装配/配置/健康 |
| `release_assets/README-快速开始.txt` | 5 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `runtime-manager/schemas/fixtures/napcat-package.json` | 2 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `scripts/build_embedding_fixture.py` | 0 | 是 | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/build_offline_payload.py` | 1 | — | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/build_release_catalog.py` | 7 | — | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/dev_webui.py` | 0 | 是 | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/eval_memory_replay.py` | 4 | 是 | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/evaluate_dialogue_attribution.py` | 5 | 是 | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/generate_message_flow.py` | 1 | — | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/probe_consolidation.py` | 4 | 是 | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/probe_embedding.py` | 0 | 是 | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/smoke_nonebot_entry.py` | 4 | — | WP11 | 探针/构建/CI/完整性门禁 |
| `scripts/validate_rust_fullchain.py` | 0 | 是 | WP11 | 探针/构建/CI/完整性门禁 |
| `stella-installer/src-tauri/src/commands.rs` | 30 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `stella-installer/src/mock/doctor-mixed.json` | 3 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `stella_project/plugins/bot_main/__init__.py` | 1 | 是 | WP02/04 | 共享消费者复核，按真实调用归属 |
| `stella_project/plugins/bot_main/ai_gateway.py` | 89 | 是 | WP05/06/07/09 | 按入口、投递、后台、装配拆分，禁止整文件机械替换 |
| `stella_project/plugins/bot_main/cometa_bridge.py` | 30 | 是 | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/config.py` | 1 | — | WP02/04 | 共享消费者复核，按真实调用归属 |
| `stella_project/plugins/bot_main/scheduling/agent.py` | 7 | — | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/scheduling/context.py` | 3 | — | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/scheduling/cron.py` | 1 | — | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/scheduling/delivery.py` | 1 | 是 | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/scheduling/models.py` | 4 | — | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/scheduling/runtime.py` | 2 | 是 | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/scheduling/service.py` | 11 | 是 | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/scheduling/store.py` | 15 | 是 | WP07 | 后台/任务/持久目标 |
| `stella_project/plugins/bot_main/status_api.py` | 4 | 是 | WP09 | 装配/配置/健康 |
| `webui/app.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/chat_ingress.py` | 4 | 是 | WP05 | WebChat通用入口回归 |
| `webui/mount.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/routers/chat.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/routers/cometa.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/routers/config.py` | 3 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/routers/conversations.py` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/routers/manage.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/routers/platform.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/cometa.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/cometa_auth.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/config.py` | 5 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/conversations.py` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/envfile.py` | 1 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/flow.py` | 5 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/groups.py` | 12 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/kb.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/platformcfg.py` | 7 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/runtime.py` | 0 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/sched.py` | 13 | 是 | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/spaces.py` | 12 | — | WP10 | 控制面/交付；QQ专属模块可保留 |
| `webui/services/system.py` | 3 | — | WP10 | 控制面/交付；QQ专属模块可保留 |

## D. 图谱风险与缺边复核

风险表以 [impact-summary.json](../reports/evidence/cross-platform-20261020/impact-summary.json) 为机器可读来源，包含直接依赖、risk、epistemic及边界。首次失败/截断与后续修正对应见 [query-resolutions.json](../reports/evidence/cross-platform-20261020/query-resolutions.json)。

实施新增源文件后重新构建图谱，再对新符号做影响分析；不得用本轮新文件不在图中的 UNKNOWN 为后续业务修改放行。
