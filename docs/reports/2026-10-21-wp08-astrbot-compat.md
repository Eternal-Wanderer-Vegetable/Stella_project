# WP08 实施记录：AstrBot 兼容

- 日期：2026-10-21（Asia/Shanghai）
- 工作分支：`codex/cross-platform-implementation`
- 基线：WP07 实现提交 `7bea280`
- 实现提交：`8e3466e`（`feat(astrbot): guard QQ plugin compatibility (WP08)`）
- 状态：WP08 定向实现与回归完成；XPLAT-IMPL 整体仍 **NOT READY**。

## 范围和结果

AstrBot 插件分发入口和 capability 工具入口都只为经验证的 OneBot v11 Bot 构造事件。pipeline 在收集并运行 QQ 插件前检查 Bot 的 adapter；工具入口同时检查 ChatContext 的 adapter 名称与实际 Bot。空 adapter、Telegram、Satori 等不进入 QQ API 插件面。`build_event` 直接拒绝未验证的 Bot。

入站消息链转换现在接受文本、mapping、常见 `type/data` 段对象和异构序列，并兼容 Plain/Text、mention/At、quote/Reply 等通用表示。OneBot 导出仍是显式的 OneBot codec，没有把 QQ API 或发送行为模拟到其他平台。

`PlatformAdapterTypeFilter` 按 adapter 类型名匹配；平台实例 ID 是连接配置标识，不能作为类型判断依据。未知类型和缺少类型字段都拒绝。`Context.send_message` 仅接受 OneBot session 与群/私聊目标；它从 Bot 注册表挑选唯一 OneBot Bot，多 OneBot 实例时 fail closed，不使用 NoneBot 默认的首个 Bot。

## GitNexus upstream impact

编辑前使用固定 GitNexus 1.6.11；先刷新索引至 WP07 基线。`build_event` 为 HIGH（5 impacted / 2 direct；命中 `handle_plugin` 流程），编辑前已在会话中提示。`dispatch`、`collect_handlers`、`_build_astr_event`、`to_onebot_message`、Context session/send helpers 的图风险为 LOW。`PlatformAdapterTypeFilter.filter` 为 UNKNOWN / 0 静态调用；源码确认 `pipeline._run_filters` 动态遍历 handler metadata 的 filters 并调用 `.filter(event, None)`，装饰器在 `filters.py` 注册此对象。回调与框架注解边界另经源码引用核对；未以 riskSharedAxes 降级风险。

提交前的 `detect-changes --scope all` 为 14 files / 60 symbols / 5 affected processes / MEDIUM。`--scope compare --base-ref main` 为 300 files / 971 symbols / 107 processes / CRITICAL，包含 WP00–WP08 的累计差异。所用 `.gitnexus/gn` 固定 1.6.11；仓库 `.gitnexus/run.cjs` 实际启动 1.6.12 并遇到 Ladybug storage version mismatch，因此 detect-changes 统一经固定启动器运行。CLI 返回摘要和受影响流程数，没有暴露 MCP 的 partial/truncated 字段；这两条命令均退出 0。

状态文档提交前 scope all 为 3 files / 7 symbols / 0 processes / LOW；compare main 为 301 files / 972 symbols / 107 processes / CRITICAL（累计包含 WP00–WP08）。新实施报告以链接和 diff 检查补证。

## 验收证据

| 命令/范围 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/astrbot_compat tests/capability/test_capability_hooks.py -q` | 373 passed。覆盖分发与工具事件构造、平台类型过滤、通用链转换、拒绝非 OneBot Bot，以及多 Bot 的 fail-closed 行为。 |
| `.venv/bin/ruff check .` | All checks passed。 |
| `.venv/bin/python scripts/check_docs.py` | 119 files / 1,223 local links / 577 anchors / 0 errors。 |
| `.venv/bin/python scripts/generate_message_flow.py` | 生成 `core/observability/flows/message-flow.9b80952673b2.json`：141 nodes、139 source-resolved、8,973 closure sites、11,899 reachable symbols。 |
| `.venv/bin/python scripts/generate_message_flow.py --check` | 生成后通过。 |
| `git diff --check` | 通过。 |

## 数据边界与未完成验收

`STELLA_HOME` 未设置，测试使用临时/fixture 数据。没有读取或迁移生产库，没有启动真实 Bot、模型或平台。没有真实平台 live、多 Bot 重启、QQ 灰度、clean VM、发布或全量 Python 验收。该兼容层只承诺已实现的 OneBot v11 插件路径；任意 AstrBot 插件的底层 API 仿真属于计划明确排除项。WP09–WP11 及外部认证仍未完成，整体 **NOT READY**。
