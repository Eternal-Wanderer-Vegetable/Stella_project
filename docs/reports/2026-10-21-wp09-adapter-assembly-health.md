# WP09 多适配器装配与健康实施记录

日期：2026-10-21（Asia/Shanghai）
实现提交：`9f75ded feat(transport): configure adapter assembly and health (WP09)`
状态：WP09 实施与本地门禁完成；跨平台 live、QQ 灰度、全量 Python、clean VM 与发布认证仍 NOT READY。

## 交付

- 新增 `STELLA_ADAPTER_MODULES`。默认只注册 `nonebot.adapters.onebot.v11`；逗号分隔的模块按配置顺序导入和注册；空值、`none`、`off`、`disabled` 关闭 Bot 适配器。启用包缺失、适配器导出错误或 Driver 不兼容时明确失败，不自动安装第三方代码。
- `pyproject.toml` 将 CLI 侧的 NoneBot adapters 列表置空，由 `bot.py` 在 `nonebot.init()` 建立 Driver 后、加载插件前注册配置项。现有 OneBot 依赖继续保留在默认依赖中；新增适配器由部署者单独安装。
- `extensions/link_monitor` 按 `(adapter type, self_id)` 隔离 Bot 状态、告警节流与探活目标。只有 OneBot V11 使用事件心跳与 `get_status()`；逐一探测每条 OneBot，避免一个健康 Bot 掩盖另一个失联 Bot。
- `link_status()` 保留旧单 Bot 字段，新增 `applicable`、`bots` 与 `connections`。非 OneBot 模式的 OneBot 专属 `connected`/`healthy` 为 `null`，非心跳适配器仍报告其连接状态、健康度为 `null`；每连接只用不透明引用。`status_api.build_payload()` 原样透传该字段，未新增存储或网络接口。
- 中英文配置与集成文档说明装配、依赖、驱动失败与健康语义。

## GitNexus

编辑前检查（GitNexus 1.6.11，当前索引绑定 WP08 的 `5ee0601`）：

- `link_status`：LOW，4 个受影响节点、2 个直接调用者、2 条流程；直接使用者为 `status_api.collect_status` 与 `webui/services/runtime.platform_link`。
- `collect_status`：LOW，1 个直接调用者（状态接口）；`setup_status_api`：LOW，6 个受影响节点，源码调用来自 `bot.py` 与 `ai_gateway.py`。
- `_on_bot_connect`、`_on_bot_disconnect`、`_refresh_on_any_event`、`link_monitor_task` 与扩展 `setup` 的静态调用图为 UNKNOWN/0。源码检查确认它们分别由 NoneBot driver 装饰器、`event_preprocessor`、APScheduler 装饰器和扩展自动发现调用；`extensions/__init__.py` 负责 import 并调用 `setup(pipeline)`，`ai_gateway.py` 在启动装配中调用 `load_extensions`。
- `bot.py` 的 Driver 无静态上游；新增 `adapter_loader` 为本地新符号。适配器装配时序直接由入口源码确认。

提交前检查：

- `detect-changes --scope all`：13 个文件、59 个符号、4 条流程，MEDIUM。
- `detect-changes --scope compare --base-ref main`：314 个文件、1,018 个符号、106 条流程，CRITICAL；这是 WP00–WP09 累计差异。GitNexus 提示符号明细列表有上限，但明确说明风险与计数覆盖全部变更。第一次 compare 出现 PARTIAL（图查询被中断），随即串行重跑，最终结果未出现 PARTIAL；没有把第一次结果当作验收。

## 验证

命令均使用临时 `STELLA_HOME=/tmp/stella-wp09-20261021`，未访问本机用户数据：

- 定向回归：
  `.venv/bin/python -m pytest tests/test_link_monitor.py tests/test_adapter_loader.py tests/test_status_api.py tests/test_deploy_cli.py tests/test_runtime_e2e.py tests/test_runtime_contract.py -q`：**73 passed**。
- `.venv/bin/ruff check .`：通过。
- `python scripts/check_docs.py`：119 个文件、1,224 个本地链接、577 个迁移锚点、0 errors。
- `python scripts/generate_message_flow.py --check`：`message-flow.9b80952673b2.json` 与源码一致。
- 解析 `pyproject.toml` 确认 `[tool.nonebot].adapters == []`。
- 隔离进程执行 `nonebot.init()` 和默认装配函数，没有运行 Bot 生命周期、打开端口或连接平台；NoneBot Driver 实际注册表只有 `OneBot V11`。
- `git diff --check` 与暂存 diff 检查通过。

## 未验收项

- 其他平台 adapter 未安装或启动；本地 Driver smoke 只覆盖仓库默认的 OneBot V11。driver 不兼容和缺失传递依赖由隔离单元测试覆盖，没有真实第三方包组合证据。
- 没有启动 QQ Bot、真实账号或模型；没有 QQ 灰度、平台 live、clean VM 或发布包验收。
- 没有运行全量 Python 测试。WP07 已记录的 Cometa worker 挂起仍是集成验收缺口；WP09 定向回归不能替代。
- 因此 XPLAT-IMPL 与整个计划继续 NOT READY，下一阶段为 WP10 控制面和交付。
