# NoneBot 跨平台接入实施记录（2026-10-20）

关联计划：[GitNexus 跨平台执行方案](../plans/2026-10-20-gitnexus-cross-platform-plan.md)；详细源码与入口清单见[执行附录](../plans/2026-10-20-cross-platform-inventory.md)。

## 当前状态

- 分支：`codex/cross-platform-implementation`
- 基线：`main@ba582a922f4d3379b6397c4c0a8d8ef3e7c3e77d`
- WP00：完成，等待阶段提交。
- 下一步：WP01 身份和注册表。
- 外部边界：没有启动 Bot、没有读取或迁移用户库；新平台 fixture/live 与发布认证尚未执行。

## WP00 — 合同冻结与基线

冻结可选平台桥接组合：NoneBot 2.5.0、`nonebot-plugin-alconna==0.62.1`、`nonebot-plugin-uninfo==0.11.2`。平台依赖不会进入默认 QQ/WebChat 安装。组合解析写入 [`requirements-platform.in`](../../requirements-platform.in) 与 [`requirements-platform.lock`](../../requirements-platform.lock)；通过 `uv pip compile --universal --python-version 3.10` 生成跨 Python/平台版本锁。官方包元数据将 Alconna 与 Uninfo 的 Python 下限标为 3.10，且依赖 NoneBot 2.5.0 或更高版本；本项目 Python 下限和组合一致。

验证命令及结果：

| 命令 | 结果 |
| --- | --- |
| `uv pip compile --python-version <3.10|3.11|3.12> -o /tmp/stella-xplat-<version>.txt requirements.txt /tmp/stella-platform-req.in`（分别运行三次） | 三个版本均解析成功。 |
| `uv run --no-project --python <3.10|3.11|3.12> --with nonebot-plugin-alconna==0.62.1 --with nonebot-plugin-uninfo==0.11.2 --with nonebot-adapter-onebot==2.4.6 python -c 'import nonebot, nonebot_plugin_alconna, nonebot_plugin_uninfo; from importlib.metadata import version; print(version("nonebot2"), version("nonebot-plugin-alconna"), version("nonebot-plugin-uninfo"))'`（分别运行三次） | 三个版本均导入成功；Alconna UniMessage 插件载入。NoneBot 未初始化警告是 smoke 进程没有创建 Bot 的预期提示。 |
| `.venv/bin/python -m pytest tests/test_conversation_identity.py tests/test_conversation_registry.py tests/test_multi_user_identity.py tests/test_private_chat_ingress.py tests/test_context_tail.py tests/test_ai_gateway_deterministic_reply.py tests/test_memory_capture_gate.py tests/test_capture_ingress_gating.py -q` | `142 passed in 5.61s`。覆盖 QQ/WebChat 身份、注册、入口、上下文、采集门冻结基线。 |
| `.venv/bin/python scripts/check_docs.py` | `119 files / 1201 local links / 577 anchors / 0 errors`。 |
| `uv pip install --dry-run --python .venv/bin/python -r requirements-platform.lock` | 95 个依赖无需变更。 |
| `uv pip check --python .venv/bin/python` | 143 个已安装包兼容，无依赖冲突。 |
| `git diff --check` 与 `feature_list.json` JSON parse | 通过。 |

本机 `STELLA_HOME` 未设置。pytest 全局夹具把用户数据根目录设为系统临时目录，空间配置也由每例临时路径隔离；测试没有打开真实数据库。

## GitNexus 编辑前影响证据

索引由固定 GitNexus 1.6.11 建立，status 为 `up-to-date`，索引提交 `ba582a9`。按目标 UID 精确查询，不能用 shared axes 降低原始 risk：

| 目标 | upstream 结果 | 边界/补证 |
| --- | --- | --- |
| `Function:core/conversation.py:conversation_key` | CRITICAL；14 impacted、6 direct、4 flows、5 modules | 直接进入会话工厂、注册、WebUI chat/stream 与 Bot addressing/private-chat 流程。 |
| `Method:core/conversation.py:ConversationRef.conversation_key#0` | UNKNOWN；0 graph edges | 通过 `rg` 与源码属性访问补证；属性在多处 DTO/数据库/任务合同中按字面引用。 |
| `Function:memory/conversation_registry.py:get_or_register_group` | UNKNOWN；0 static callers | `rg` 仅找到定义与测试；现有群入口未接入注册表，WP01/WP05 必须显式迁移。 |
| `Function:memory/ownership.py:scope_for_chat_context` | HIGH；5 impacted、2 direct、1 flow，`maybe_plan` | 权限谓词不能在未知主体时扩大可见范围。 |
| `Function:memory/pre_processors.py:record_message` | CRITICAL lower-bound；18 impacted、4 direct、9 flows、4 modules | 索引丢弃3个接收者类型未知的调用点，真实影响可能更大。 |

## 下一步

WP01 修改前刷新 GitNexus 图并重跑相关 UID 的 upstream impact。身份/注册实现需要保持 QQ/WebChat 旧键 alias，明确规范数组编码及 ID 字符串语义，再按不透明 ID、父级/线程、同号多 Bot、并发分配和重启恢复添加正反例。生产迁移留在 WP03 的临时副本验证阶段。
