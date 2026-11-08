# 能力工具回复被投递门拒绝的排查记录（2026-11-07）

状态：**已修复（2026-11-08）**，见文末「修复（2026-11-08）」。前文为 2026-11-07 的原始排查记录。

发现于 Ligamina（插件联邦运行时）的 P4-05 真实平台联调：Stella 通过内置 MCP 客户端调用 Ligamina 暴露的插件工具。工具执行成功、回复已生成，但消息没有出现在 QQ 群里。

## 现象

- 群成员 @Stella 发送「帮我投掷两个六面骰子」。
- 路由命中能力：`🧭 [Router] Route(chat+memory+tool+no-generation ['dice.roll'] via rule) — 关键词命中能力 ['dice.roll']`。
- Comes 成功执行：`🔧 [Comes] dice.roll → partial (26891ms, agent, 2 次工具调用) summary='掷骰结果：投掷2个六面骰子，点数为【10】。'`。
- 日志出现 `✨ [即将发送给 QQ 的台词]: 掷骰结果：投掷2个六面骰子，点数为【10】。`，之后**没有任何发送、回执或错误日志**，群里也没有消息。

## 证据：flow trace

`StellaData/turn_trace.db` 中该轮 trace 的末尾节点（只读查询 `flow_events`）：

```
prepare.direct   decision  succeeded  hook_reply
turn.direct_silent decision skipped   direct
chat.runtime     finish    succeeded
send.prepare     decision  succeeded  普通回复
send.plan        decision  blocked    invalid_delivery_plan  "delivery source 未获准"
ingress.receive  trace_end closed     delivery_plan_rejected
```

即：回复在 `send.plan` 被投递计划封存拒绝，`ai_gateway` 按 `invalid_delivery_plan` 分支静默返回（只写 flow trace，不写普通日志）。同一窗口内全部 2 个 `hook_reply` 轮次都以同一原因被拒绝（两次都是本次联调的骰子请求）。

## 根因

1. **能力路由一律跳过生成。** `capability/router/rules.py:158-160`（关键词命中）与 `capability/router/semantic.py:300-302`（语义命中）返回的 Route 都是 `requires_generation=False`。
2. **工具结果直接成为回复。** `capability/hooks.py:291-315` 把成功结果的 summary 写入 `ctx.reply` / `ctx.lines`；随后 `core/runtime/turn_service.py:353-356` 以 `prepare.direct` / `hook_reply` 走 `DIRECT`，本轮不再调用生成模型。
3. **直回路径没有设置投递来源。** `ctx.delivery_source_kind` 只在生成路径设置（`turn_service.py:728` 设为 `model`，超时/异常分支设为 `trusted-server-fallback`）。`core/social/delivery.py:173-175` 的回退逻辑只在 `ctx.llm_call_count > 0` 时取 `model`；Comes agent 内部的模型调用不计入该计数，于是来源成为 `unknown`。
4. **投递门拒绝。** `seal_delivery_plan` 只接受 `_TRUSTED_SOURCE_KINDS = {"model", "trusted-server", "trusted-server-fallback", "proactive-contract"}`（`core/social/delivery.py:66-68`），对 `unknown` 抛出 `DeliveryPlanError("delivery source 未获准")`（`delivery.py:214-215`）。

**影响范围**：所有经能力路由、由 Comes 产出直接回复的工具结果都会被静默丢弃，不限于 MCP，也包括 AstrBot 兼容层插件工具。推测是 `705f428 feat(router): mark deterministic and generation routes` 引入的直回路由与 `core/social/delivery.py` 的投递来源门控叠加后出现的回归；尚未逐提交二分确认。

## 修复建议

二选一，需要按投递信任模型决定：

- **最小修复**：在 `capability/hooks.py` 写入 `ctx.reply` 处同时设置 `ctx.delivery_source_kind = "trusted-server"`，表示回复由服务端能力执行产出而不是模型直出。
- **语义更清晰的修复**：新增来源 `capability-tool`（或类似名称），在 hooks 中设置，并加入 `_TRUSTED_SOURCE_KINDS`；如需区分外部 MCP/插件文本，可只对允许直出的能力放行，其余仍走生成路径改写。

无论哪种，建议同时：

- 让 `invalid_delivery_plan` 分支在普通日志中留下一条 WARNING（当前只写 flow trace，现场极难发现）。
- 增加回归测试：能力路由命中 → Comes 成功 → `prepare.direct` → 投递计划封存成功并调用 outbound send。

## 复现条件（联调配置，均可撤销）

- `StellaData/config/mcp.toml`：`[servers.plugins]`，`transport = "streamable_http"`，`url = "http://127.0.0.1:63900/mcp"`，`auth_env = "PLUGIN_MCP_TOKEN"`，`allowed_tools = ["cmd.field-nonebot-roll.rd"]`。
- `StellaData/config/capabilities/plugin-tools.toml`：`dice.roll` 能力，关键词「掷骰」「骰子」，provider 为上述 MCP 工具。
- 启动时的进程环境覆盖（未修改 `StellaData/.env`）：`MCP_ENABLED=true`、`PLUGIN_MCP_TOKEN=<本地令牌>`、`NO_PROXY=127.0.0.1,localhost`，并把旧 Ligamina 桥接扩展的 `*_ENABLED` 设为 `0`。
- 撤销：删除上述两个配置文件，按原方式启动即可。

## 联调中的其他发现

- **本机系统代理会拦截回环 MCP 请求。** Stella 环境中的 httpx 会经 Windows 系统代理访问 `127.0.0.1`，MCP 连接得到代理返回的 `502 Bad Gateway`（日志只显示 `unhandled errors in a TaskGroup`）。设置 `NO_PROXY=127.0.0.1,localhost` 后恢复。建议 MCP 客户端对回环地址显式禁用代理，或在诊断信息中展开 ExceptionGroup 的子异常。
- **只结束 bot.py 主进程会遗留 Cometa worker。** 子进程 `cometa.worker` 继续持有实例租约，新启动的 worker 报 `StoreBusyError: 已有存活 worker` 并退出，任务认领停摆。按进程树结束（`taskkill /T`）可避免。建议主进程退出时确保回收 worker，或在注册时识别并接管父进程已不存在的旧 worker。

## 修复（2026-11-08）

采用“语义更清晰”的方案，并补上同次联调发现的第二个问题。

1. **新增投递来源 `capability-direct`。** `core/social/delivery.py` 定义 `CAPABILITY_DIRECT_SOURCE_KIND` 并加入 `_TRUSTED_SOURCE_KINDS`；`capability/hooks.py` 的 `_set_direct_reply` 在写入直回文本时设置 `ctx.delivery_source_kind`。没有借用 `trusted-server`：直回文本来自能力执行（可能是外部 MCP / 插件输出），不是服务端固定文案，单列来源便于审计区分。归因守卫（`attribution_guard_hook`）的可信直回集合同步加入该来源，shadow / enforce 模式下不会把它当作模型直出再做归因。
2. **投递计划被拒时写 WARNING。** `handle_chat` 与 `handle_private_chat` 的 `invalid_delivery_plan` 分支除 flow trace 外记录一条普通日志（含来源与 trace id），不再静默。
3. **参数全为可选的工具不再“无参直调”。** `capability/comes/executor.py` 的 `can_direct_call` 原先只看必填参数：插件命令 `组队昵称` 声明 `nickname: str = ""`，schema 无必填字段，于是跳过模型、以 `{}` 调用，插件只回用法说明，Comes 仍记为 success。现在非确定性路由只有在没有任何待填参数（无必填、可选参数也已由任务给出）时才直调；确定性路由的槽位由路由器抽取，规则不变。代价：始终带可选 `arguments` 字段的 MCP 命令工具，即使无参也会多一次受限 agent 模型调用。

验证：

- 新增回归测试 4 项（`test_social_delivery`、`test_capability_hooks`、`test_comes_executor`），在未修复代码上均失败、修复后通过；这三个文件共 109 项通过。
- 全量 `pytest tests -n auto --dist loadgroup`：4323 通过；6 项失败中 5 项在未修改的 main 上同样失败（corona / gravitas / webui 的环境问题，与本次改动无关），第 6 项为消息流 manifest 漂移，已运行 `scripts/generate_message_flow.py` 重新生成。
- 联调复验（插件运行时仓库的 `lab/field/run_stella_mcp_experiment.ps1 -Level comes`）：本分支代码下，掷骰、复读、组队昵称经 Comes + 本地模型各 3/3 通过（修复前组队昵称 0/3）。

另外留意：`core/runtime/turn_service.py` 的 sufficiency guard 在 enforce 模式下设置 `delivery_source_kind = "memory-sufficiency-abstention"`，该值同样不在 `_TRUSTED_SOURCE_KINDS` 中，弃答文案可能以同样方式被投递门拒绝。本次未改动，需单独确认。
