# Feature Parity 清单（M0 冻结）

> 状态标记：`⬜ 未迁移`、`🔷 过渡兼容`、`✅ 已迁移`、`🔒 永不迁移（保持原实现）`。
> 「阶段」列即负责人角色（M0–M9，见 plans/2026-09-27-gitnexus-plan-cortico-runtime-migration.md §7）。
> 行号基线：`feat/cortico-runtime-migration` @ `acd5aee`（计划证据基线 `390987e` 的漂移文件见 baseline-report.md，均不在本清单主符号文件内）。
> 本清单由四路源码普查生成（QQ 入口 / WebUI API / 扩展配置 / 发行渠道），是迁移的功能冻结基线：**任何未在本清单出现的入口视同「未归类」，迁移期间不得静默删除或改变行为**。

## 0. 命名决策（记录在案）

计划文本中的 `runtime/cortico/` 路径调整为 **`node_runtime/cortico/`**：`runtime` 是发行链保留目录名（嵌入式 Python 运行时），被 `.gitignore:84`、`scripts/build_release_package.py FORBIDDEN_PARTS`、`scripts/check_release_archive.py FORBIDDEN_COMPONENTS`、`.github/workflows/release.yml` rsync `--exclude 'runtime'`、`.dockerignore` 五处封死。计划 §10 允许「新增文件名微调，责任边界和验收不省略」。责任边界不变：`node_runtime/cortico/` 承载 host、registry、persona、adapter、provider-bridge 与 TS 测试。

## A. QQ 消息入口（全部在 `stella_project/plugins/bot_main/ai_gateway.py`，群聊 only，无私聊/notice/request handler）

| 旧入口 | 数据归属 | 旧行为 | 目标入口 | 测试/人工步骤 | 阶段 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `group_silent_listener` priority=0 block=False（:392）handler `record_group_chat`（:395-451） | memory.db `group_messages` | 白名单群、非自身回显、非 `/` 开头；空文本仅识图可用时按 `[图片]` 落库；source_kind=AT_MENTION(is_tome)/PASSIVE；触发 record_message、proactive.record_message/record_tome、reset_no_reply、session_touch、expression_learning.note_passive_message、participation observe（命中 ALLOW_LLM 时 `_spawn_participation_speak`） | 不迁移：落库与统计留 Python 接入层；participation 触发产生的生成工作经 RuntimeFacade | `tests/test_bot_self_source.py`、`tests/test_source_kind.py`、人工：群内发言后 `group_messages` 有行 | M6 | ⬜ |
| `chat_handler` priority=3 block=True（:516）规则 `is_chat_trigger`（:454-473） | memory.db + usage_store | @ 触发主链路：`_plugin_handled_msgs` 跳过（:522）→ 群锁（:526）→ ChatContext（:531）→ reply gate（:545）→ 按需整合（:558）→ 预算拦截 `budget_blocked(ROLE_CHAT)` pause_all 静默 return（:575-580）→ `pipeline.run`（:584）→ planner_wait 早退（:596）→ 空行兜底「......？」（:601）→ 记账/学习/BOT_SELF/压缩调度（:606-631）→ 首行引用+分行间隔发送（:633-647） | `handle_chat` → RuntimeFacade.submit | `tests/test_pipeline_compose.py`、`tests/test_full_workflow.py`、`tests/test_ai_gateway_deterministic_reply.py`；人工：@Bot 普通问答 | M4 | ⬜ |
| `plugin_handler` priority=2 block=False（:494） | astrbot_compat registry | AstrBot 插件分发（`should_dispatch`/`dispatch`），命中记 `_plugin_handled_msgs`（256 LRU）让 chat 跳过 | 不迁移：插件分发留 Python 接入层 | `tests/astrbot_compat/` 全套；人工：B 站插件命令 | 🔒（接入层保留） | ⬜ |
| `toggle_handler` priority=1（:864） | proactive state | 安静/恢复主动发言命令，管理员校验，回确认语 | 不迁移（确定性命令，零生成） | 人工：@Bot 安静 → 不再主动；恢复 → 恢复 | 🔒 | ⬜ |
| `addressing_handler` priority=1（:717） | user_profiles | 设置/清除/查询个性化称呼；改他人需群管理员；reply+text 引用回复 | 不迁移（确定性命令） | `tests/test_addressing*.py` | 🔒 | ⬜ |
| `capability_handler` priority=1（:962） | capability registry | 「你能做什么」等 13 句直读能力注册表，>320 字转图，不走 LLM | 不迁移（确定性查询） | `tests/test_capability_query.py` | 🔒 | ⬜ |
| `reload_handler` priority=1（:1094） | plugin registry | 热重载单个插件或参与评分 TOML（双开关门控） | 不迁移（确定性管理命令） | 人工：@Bot 重载插件 <名> | 🔒 | ⬜ |
| `scheduling_handler` priority=1（:1229） | scheduling/tasks.db | 「定时」前缀 14 action 分派（见 E 节） | 不迁移（命令面）；生成型执行入口迁 RuntimeFacade（E 节） | `tests/scheduling/test_scheduling_commands.py` 等 | M6 | ⬜ |

启动期 import 副作用（装配顺序敏感，迁移必须保序）：pipeline 装配（:160-269）→ status_api 挂载（:274）→ 周度压缩注册（:283）→ `ensure_v2_schema`（:300）→ usage_store.install（:311）→ 可选 DB 清理（:324）→ checkpoint 对齐（:339）→ 消息清理补跑（:360）。优先级互斥自检：`_assert_listener_priorities`（:867）与五个 priority-1 规则两两机械互斥断言。

## B. 主动发言链路

| 旧入口 | 数据归属 | 旧行为 | 目标入口 | 测试/人工步骤 | 阶段 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `_proactive_at_user`（:1763-1882） | memory.db + proactive state | `can_speak(group,"at")` 门禁（总开关→AT 分开关→运行时静音→睡眠→冷却→新消息门槛）→ `pick_target` 配额/冷却/退避 → 群锁 → ctx trigger="reply" intent="proactive_at" → pipeline.run → `is_proactive_skip` 判弃 → 多行合并一句 → recently_spoken 去重 → `bot.send_group_msg`（at+空格，无引用）→ 发出即计数 record_at → 后台 `_check_reply_later` 回访退避 | RuntimeFacade.submit（保持 trigger/intent 语义） | `tests/test_proactive_at_flow.py`、`tests/test_proactive_gate.py`、`tests/test_proactive_target.py` | M6 | ⬜ |
| `_proactive_speak_for_group`（:2082-2227） | 同上 | 触发源：APScheduler `proactive_speak_job`（:2232）与 `_spawn_participation_speak`（:2041，PASSIVE observe 命中）；`can_speak(group,"join")` + 概率掷骰（skip_dice 时跳过）→ 群锁 → 锁内 reply gate evaluate+start/finish → 前置 force maybe_consolidate + sleep(1.0) → ctx user_id=0 trigger="proactive" instruction=参与评分文案+证据块 → is_proactive_skip → 超 PROACTIVE_MAX_LINES 合并 → 去重 → 逐行发送（无引用，行间 SEND_INTERVAL）→ 记账/BOT_SELF/schedule_compact | RuntimeFacade.submit | `tests/test_proactive_rules.py`、`tests/test_participation.py`、`tests/test_reply_gate.py` | M6 | ⬜ |
| `_announce_sleep_transition`（:1885-1920） | proactive state | 睡眠/苏醒播报，每类每日一次，**绕过 Pipeline 直发** | 🔒 不迁移（零生成确定性发送） | 人工：跨睡眠时段观察播报 | 🔒 | ⬜ |

## C. WebChat 与 WebUI API（均挂 Bot 同一 uvicorn 端口；统一 envelope `{"status","message","data"}`）

### C.1 WebChat（`webui/routers/chat.py` + `webui/chat_ingress.py`）

| 旧入口 | 数据归属 | 旧行为 | 目标入口 | 测试/人工步骤 | 阶段 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /api/v1/chat`（chat.py:110，JWT） | memory.db 虚拟群 -1 | SSE：`run_started{}` → `complete{lines,thought}`/`error{message}`；空消息直接 JSON 不走 SSE；120s `asyncio.wait_for` 超时→error「回复超时」；仅 RuntimeError/TimeoutError 产生 error 帧 | `run_turn` → RuntimeFacade.submit | `tests/webui/test_webui_chat.py`；人工：WebUI 聊天 | M4 | ⬜ |
| `run_turn`（chat_ingress.py:64-97） | 同上 | 模块级锁只包 `pipeline.run`；WEBCHAT_GROUP_ID=-1、WEBCHAT_SPACE="webchat"（首用原子写 toml）、WEBCHAT_USER_ID=800_000_000；输入 source_kind=AT_MENTION msg_id=0；回复逐行 BOT_SELF；返回 `{lines,thought}`（无 ts，docstring 有误以代码为准） | facade 提交，锁边界归 RuntimeFacade | 同上 | M4 | ⬜ |
| `GET /api/v1/chat/session`（chat.py:37） | memory.db | `{group_id:"-1",message_count,space:"webchat"}` | 🔒 不变 | `tests/webui/test_webui_chat.py` | 🔒 | ⬜ |
| `GET /api/v1/chat/messages`（chat.py:54） | 同上 | before_id/limit(1-200,默认50)，按 id 升序 | 🔒 不变 | 同上 | 🔒 | ⬜ |
| `POST /api/v1/chat/reset`（chat.py:82） | 同上 | 删虚拟群消息段 + consolidation_state 行；**长期记忆不动**；M4 起须先 fence/cancel/drain 在途轮次再清运行记录，epoch 递增 | 🔒 接口不变，语义增强 | 同上 + 新增 `tests/runtime/` | M4 | ⬜ |

### C.2 WebUI 其余端点（迁移不改变任何 schema；runtime 仅新增诊断字段）

| 组 | 端点 | 鉴权 | 阶段 | 状态 |
| --- | --- | --- | --- | --- |
| auth（auth.py） | setup-status / setup / login / desktop-session / me / logout / PATCH account | 公开+限流（三桶共享容量 429）/ JWT | 🔒 | ⬜ |
| status | GET /api/v1/status（status.py:32，`/stella/status` 聚合超集+webui 段，绝不 500） | JWT | M7 加 runtime 段 | ⬜ |
| usage | GET /usage/today、/usage/daily | JWT | 🔒 | ⬜ |
| providers | GET /providers/runtime | JWT | 🔒 | ⬜ |
| platform | GET /platform/link | JWT | 🔒 | ⬜ |
| plugins（只读） | GET /plugins | JWT | 🔒 | ⬜ |
| conversations | /conversations/groups、/conversations、/conversations/context | JWT | 🔒 | ⬜ |
| trace | /trace/memory、/trace/memory/{id}、/trace/participation | JWT | M7 加 runtime trace 映射 | ⬜ |
| logs | /logs/history、/logs/live（SSE，`id:` 帧偏移+Last-Event-ID 续传+15s 心跳） | JWT | 🔒 | ⬜ |
| config | schema、GET/PUT config、providers endpoints/roles/models/test、platform/onebot、spaces CRUD、groups/bindings/mute/unmute、system/restart（desktop/self/manual 三态）、system/doctor | JWT+审计 | M7 | ⬜ |
| manage | mcp/servers×7、skills×5、knowledge-bases×8、scheduling×10 | JWT+审计 | M6（scheduling 语义）、🔒 其余 | ⬜ |
| plugins_mg | enabled/reload/config/readme/install/install-upload/DELETE/market/plugin-sources×4 | JWT+审计 | 🔒 | ⬜ |
| app 级 | /api/v1/openapi.json、/api/v1/docs（无鉴权）；SPA catch-all（static.py:185，必须最后注册，api 前缀硬 404） | 无 | 🔒 | ⬜ |
| 宿主级 | GET /stella/status（status_api.py:260，无 token 仅回环，非回环 403；桌面壳健康检查打这里） | 仅回环 | M7 健康涵盖 Node host | ⬜ |

已知契约漂移（Q1 保留另修，不混入迁移）：`openapi-v1.yaml` 落后实现约 60 端点；restart 模式 yaml 缺 `"self"`；`chat_ingress.py:65` docstring 的 `ts` 字段不存在；`plugins_mg.py:93` 注释引用不存在的 `/api/v1/files`。

## D. 调度子系统（`stella_project/plugins/bot_main/scheduling/`，独立 SQLite `STELLA_HOME/scheduling/tasks.db` WAL）

| 对象 | 旧实现 | 迁移决定 | 测试 | 阶段 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 任务类型 | `reminder`（objective 即文案直投）/ `agent`（有界 Agent：墙钟 300s/模型 4 轮/工具 8 次/输出 1200 字，agent.py:111-161） | 🔒 业务 store/lease 不变；agent 的生成型工作提交统一 RuntimeFacade | `tests/scheduling/test_scheduling_agent.py` | M6 | ⬜ |
| 运行状态机 | queued→claimed→running→ready→sending→sent；silent/failed/skipped/cancelled；sending 后进程死亡→delivery_unknown（终态，绝不自动重投） | 🔒 全保留；runtime 记录投递状态另记，generated≠delivered | `tests/scheduling/test_scheduling_delivery.py`、`test_scheduling_store.py` | M6 | ⬜ |
| 租约 | worker_lease 单行表 TTL 300s；run 级 renew_lease；`recover_expired_leases`（sending 过期→delivery_unknown） | 🔒 保留 | 同上 | M6 | ⬜ |
| 认领/配额 | `claim_next_run` 单事务（清扫→群内互斥→每日配额 40→认领+1）；Task.revision 乐观锁 | 🔒 保留；与新 runtime 无重复领取 | 同上 + `tests/runtime/test_session_ownership.py` | M6 | ⬜ |
| 投递 | DeliveryService.deliver：空+on_content→silent；ready→sending（平台调用前持久化）→发送（超时/异常→delivery_unknown）→sent（记回执）；无 receipt 合法成功 | 🔒 保留 | `test_scheduling_delivery.py` | M6 | ⬜ |
| 执行门控 | `can_speak_for_scheduled` 严格门控 fail-closed；执行前抢共享群锁 `_group_locks`（runtime.py:250-260，与 @ 回复/主动发言互斥） | 🔒 保留 | `test_scheduling_gate.py`、`test_scheduling_runtime.py` | M6 | ⬜ |
| 错过补跑 | `latest`（agent 默认）/`all`（reminder 默认），单轮上限 20 | 🔒 保留 | `test_scheduling_runtime.py` | M6 | ⬜ |
| 指令面 | 「定时」14 action：help/list/add/add_agent/show/edit/pause/resume/cancel/run_now/history/allow_tool/deny_tool | 🔒 不变 | `test_scheduling_commands.py` | 🔒 | ⬜ |
| 权限 | 每群 8 任务/每用户 3/每日每群 40；全局管理员；跨群拒绝并审计 | 🔒 不变 | `test_scheduling_service.py` | 🔒 | ⬜ |
| 启动恢复 | `_start_scheduling`（ai_gateway.py:1609）失败只停用本功能；到期任务交接语义在 M6 明确四态（到期交接/任务取消/生成后投递/投递不明） | M6 定义并测试 | 新增 | M6 | ⬜ |

## E. 领域能力（Python 服务保留，经 prepare/finalize 被新运行时调用）

| 对象 | 旧入口/实现 | 不变契约 | 测试 | 阶段 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 记忆 V1/V2 | `MEMORY_V2_ENABLED=true` 默认；pipeline 内双分支 + `record_trace`；V1: build_user_context 旧检索；V2: retrieve_memories[_emb] | 两分支、空间隔离、reset/重启不因 Core 历史改变语义 | `test_prompt_builder_v2.py`、`test_retrieval_v2_and_schema.py`、`test_session_context*.py` | M5 | ⬜ |
| 会话摘要/压缩 | build_context（pre p=50）+ session_compact schedule_compact | 进程内摘要生命周期、cache key（session_id+history_version+mode+policy_version） | `test_session_context.py`、`test_session_context_cache.py`、`test_session_compact.py` | M5 | ⬜ |
| 整合 Consolidator | force maybe_consolidate（chat :558 / proactive :2129）+ consolidation_drain（:2326） | 无重复摘要、无重复记忆写入 | `test_consolidator_core.py` 等 | M5 | ⬜ |
| 能力/Comes | activate_capabilities（pre p=45）：Router → gather(memory/comes/skills, return_exceptions=True) → 隔离检查 | 并行异常语义、`_set_direct_reply` 直回短路（0 生成）、知识隔离、绝不抛异常 | `tests/capability/`（18 文件） | M5 | ⬜ |
| 知识库 | knowledge.search 证据块（≤4 items/600 tokens/700 chars）；排除直回 | 证据预算、隔离检查泄漏即清空 | `tests/knowledge/` | M5 | ⬜ |
| Skills | SKILLS_ENABLED=false 默认；sandbox 模式 fail-closed；import 期 fail-fast 校验 | 执行模式校验时序 | `tests/skills/`（10 文件） | M5 | ⬜ |
| MCP | MCP_ENABLED=false 默认；provider 按 kind 分派 | 连接/关闭顺序、显式允许清单 | `tests/capability/test_mcp_*.py` | M5 | ⬜ |
| Vision | describe_images_hook（pre p=60）；VISION 角色默认 none=关 | 与 ctx.image_sources/raw_event 绑定 | `tests/test_vision.py` | M5 | ⬜ |
| Planner | RestrictedPlanner；PLANNER_MAX_LLM_CALLS_PER_TURN=2 硬上限（pipeline :256）；WAIT 条件（planner.py:163） | 调用计数不跨进程丢失；WAIT→silent 有类型 | `tests/test_planner.py` | M2/M5 | ⬜ |
| 表达学习 | note_passive_message/on_reply_sent（发送路径 :614-621） | 副作用顺序保留 | `test_expression_*.py` | M4 | ⬜ |
| 参与/回应检测 | observe（priority 0 内）+ `_check_reply_later` 回访 | 不新增触发器 | `test_participation.py`、`test_reply_detection.py` | M6 | ⬜ |

## F. 扩展与插件兼容面（冻结候选 = 外部可依赖公开接口）

1. `extensions/<name>/__init__.py` 暴露 `setup(pipeline)`；`load_extensions(pipeline, ext_dir)` 失败不阻断（extensions/__init__.py:19）。当前唯一扩展 link_monitor 不挂钩不换 backend。
2. Pipeline 公开面：`register_pre_hook/register_post_hook(hook, priority)`（降序、默认 10）、`set_llm_backend`、`set_planner`、`run(ctx)`、`system_prompt`、`system_prompt_resolver`、`ctx.reply` 非空短路。→ M2 提取为兼容 facade，`run` 在 cortico 模式路由新运行时。
3. `capability.hooks.register(pipeline)` + HOOK_PRIORITY=45；调用方不得再单独注册 build_user_context（会双跑）。
4. `memory.pre_processors.{record_message,build_context,build_user_context}`、`memory.post_processors.{parse_output,bad_phrase_filter,split_lines,log_thought,parse_raw_output}`。
5. `from config import <KEY>` 星号再导出面 + `.env` 全键（behavior-contract §6）。
6. `core.llm.{ROLE_*,backend_for,gate_of,embedding_gate,acquire,snapshot,fallback_states}`。
7. ChatContext 字段集（behavior-contract §5）。
8. astrbot_compat 公开面（loader/registry/pipeline.dispatch/events/llm_tools/render）。
9. `/stella/status` 载荷与 `link_status()` 键集（键存在值可 None）。
10. NoneBot priority 0/1/2/3 顺序不变量；`plugins.bot_main.ai_gateway.pipeline` 模块单例 import 路径（双路径回退）。
11. LLM 输出协议 `<thought>/<action>/<reply>`、`FALLBACK_REPLY="......？"`、MAX_REPLY_LINES 分段、BAD_PHRASES。

## G. 模型部署模式

三端点槽（CHAT/MEMORY/VISION × BASE_URL/API_KEY/MODEL/KIND(local|online)/CONCURRENCY/TIMEOUT，settings.py:1108-1182，旧前缀回落）× 七角色绑定（CHAT/ROUTER/PLUGIN/COMPACT/CONSOLIDATION/EXTRACT/VISION × ENDPOINT/MODEL/TEMPERATURE/MAX_TOKENS/FALLBACK_ENDPOINT；VISION 默认 none=关）。embedding 恒本地不走槽。预算：LLM_DAILY_TOKEN_BUDGET=0（不限）、BUDGET_SCOPE=online、EXHAUSTED_ACTION=pause_memory（pause_all 时 QQ 对话静默不回、agent 任务 failed）。fallback：LLM_FALLBACK_ENABLED=true 冷却 300s。
迁移决定：🔒 全部保留；provider 桥只消费 backend_for(ROLE_CHAT) 的 generate，不改注册/调度/降级逻辑。测试：`test_llm_registry.py`、`test_cost_gates.py`、`test_usage_accounting.py`。阶段：M5。

## H. 生命周期与状态

| 项 | 旧行为 | 迁移 | 阶段 | 状态 |
| --- | --- | --- | --- | --- |
| bot.py 启动序 | LAUNCH_TOKEN→json sink→wait_for_parent_exit→replace_running→astrbot shim→record_run→nonebot.init→加载插件（全部 import 副作用）→status_api 补挂→startup 钩子（scheduling/hot-reload/stop-watcher→astrbot 插件→embedding→capabilities MCP→knowledge→skills→Router 预热）→WebUI 最后挂载 | M7 插入 runtime supervisor：配置/服务完成→Node handshake→接收生成工作 | M7 | ⬜ |
| bot.py 关闭序 | nonebot 实际按注册**逆序**执行：clear_pid→renderer→embedding→terminate_plugins→mcp_runtime→_graceful_shutdown（注释声称顺序执行与实现不符，Q1 保留） | M7：停接入→drain→关 Core/桥→原资源关闭；保序验证 | M7 | ⬜ |
| status_api | version/instance_id/pid/uptime/allowed_group_count/link/scheduler/usage/capabilities/skills/runtime；不含 token、群号、消息、prompt | M7 加 runtime 模式/健康/排队/最近失败/trace 兼容字段 | M7 | ⬜ |
| 停止哨兵 | 0.5s 轮询 stop 文件→should_exit，手工降级 os._exit(0)；uvicorn timeout_graceful_shutdown=5（NapCat 反向 WS 挂死防护，勿删） | 🔒 保留 | 🔒 | ⬜ |
| 后台任务 | reply_check、schedule_compact、consolidator、Router 预热、link_monitor 60s 探活、expression_sweep、session_idle、proactive tick、participation tick、trim_group_messages（cron 4 点） | 🔒 全保留；shutdown 等待语义保留 | 🔒 | ⬜ |

## I. 发行渠道（M8 逐项纳入 Node22+ 与 cortico 产物）

| 渠道 | 产物/入口 | 需要的改动（M8 执行，M0 仅冻结） | 状态 |
| --- | --- | --- | --- |
| CI | ci.yml lint/security/test/cli/windows-native | 新增 cortico job（node22+pnpm：typecheck/test/build）；windows-native 需 Node 供子进程收割断言；dashboard_ci path filter 加新目录 | ⬜ |
| Release 主线 | release.yml：dashboard→offline-payload→installer(2×2)→build 总装；rust-wheel、cli 双平台 | 新 build-cortico job；offline payload 登记产物；installer staging；`--exclude 'runtime'` 决策（node_runtime 名已避让）；六类资产+CLI 完整性守卫 | ⬜ |
| Windows OneClick | 4 exe（python/rust × online/offline） | Node22+ 编译 TS + vendor 快照纳入；python.rs Node 引导 | ⬜ |
| Standalone | 2 zip + start.bat 引导（PY 3.12.10 + SHA256、deps marker、Rust wheel 侧车） | start.bat Node 引导段；COMMON_DIRS 加 node_runtime/vendor（现 FORBIDDEN_PARTS 只禁组件名 `runtime`，`node_runtime` 合法）；build_offline_payload MANIFEST 登记 | ⬜ |
| Docker | python:3.12-slim 单阶段（无 Node！）+ compose + entrypoint 拒启守卫 | 多阶段构建或 Node 层；.dockerignore 处理；冒烟补 cortico 启动检查 | ⬜ |
| 桌面 | Tauri NSIS：installer-hooks POSTINSTALL 装载；desktop-session 免登录；健康检查 `/stella/status` | Node 解压/装载段；版本三方一致校验扩展 | ⬜ |
| WebUI zip / CLI 包 | 独立 zip；CLI Windows zip/Linux tar | CLI 包是否带 Node 决策 | ⬜ |
| 辅助 | release-memory-rust / release-llama 工作流 | 命名不冲突即可 | ⬜ |

配套钉死约束（改发行物必过）：`tests/test_product_profiles.py`（profile 组件语义）、`test_env_schema.py`/`test_deploy_init.py`（.env.example 披露钉底）、`test_release_layout.py`、`test_release_archive.py`、`test_bootstrap.py`、`python_runtime_constants_sync_with_start_bat`（双 python.rs 常量同步，加 Node 常量须收敛单源）。

## J. 未归类入口（本次普查发现的隐藏面，全部保留）

webui 独立模式（scripts/dev_webui.py，无管线时聊天端点报错）；echo/single_session 内置插件；外部 AstrBot 插件动态命令（data/plugins，随安装变化不可静态枚举）；OneBot 反向 WS `ws://host:port/onebot/v11/ws`；渲染服务（RENDER_*，Chromium 孤儿进程收割）；AstrBot LLM 服务（ASTRBOT_LLM_*，插件侧 llm 调用走 PLUGIN 角色）。
