# Corona / Nucleus 实施 CN05 — 配置事务、应用操作与一次恢复

日期：2026-10-23（Asia/Shanghai） · 分支：`codex/corona-nucleus-implementation` · CN05 基线：`ff9d1bc`

**实现包状态：代码与定向回归完成；全量 Python 门禁 NOT GREEN，CORONA-IMPL 继续 in progress / NOT READY。** 旧入口仍是默认。本包不迁移业务路由，也不做业务数据库迁移。

## GitNexus 与编辑风险

编辑前 GitNexus 1.6.12 对齐 CN04 HEAD。`webui/services/envfile.py:write_values` upstream impact 为 **CRITICAL：12 impacted / 6 direct callers / 6 processes / 2 modules**；实现保留该共享写入路径不动，配置事务使用 Corona 自有的 CAS/journal/原子替换路径。`webui/routers/config.py:config_update` 为 UNKNOWN/0（装饰器注册）；已从 `webui/app.py` router mount 和 `config_service.update` → `envfile.write_values` 源码审计调用路径。`build_config_revision` 为 UNKNOWN/0，源码引用审计确认其 managed builder 由新配置存储和既有合同测试使用；增加纯文本 override 仅供候选 `.env` 预检，不改写 legacy writer。

`CoreSupervisor.start` 为 LOW（4 个图边可见直接调用者；context 提示另有 6 个接收者类型未解析调用边，实际影响可能更高）；其 `_run` 为 LOW / 5 impacted / 1 lifespan process。调整前已复核对应上下文。未发现需在本包编辑的 HIGH/CRITICAL 入口；GitNexus 是下界，动态路由、装饰器与类型未知边均用源码补证。

## 实现

- 新增 `corona.config_store`：实例私有 SQLite 控制元数据、revision/CAS、幂等键、AST 配置 schema 与显式 provider/OneBot 字段、敏感值红acted视图、外部编辑冲突检测、immutable revision 文件和 `.env` PREPARED/COMMITTED journal。替换使用私有唯一临时文件、fsync 与原子 rename；启动恢复区分 replace 前后、删除与回滚，并在外部新编辑存在时拒绝覆盖。
- 候选配置先用 `build_config_revision(source_text_overrides={".env": ...})` 纯预检，不先碰活跃文件。空值表示继承/删除；profile overlay / 环境来源变更与 Corona 保存竞争时执行冲突保护。
- 新增 `corona.operations`：apply/restart/core start/stop 共用一个串行活动操作槽，持久化接受记录、幂等响应、阶段事件和可续读序号。Apply 校验候选后 drain/stop 旧代，启动目标 revision 并要求健康身份精确匹配 revision；失败仅尝试一次上一已应用配置恢复，终态 `rolled_back` 与 `succeeded` 区分。新增 `core_reachable` 以带身份的健康探针区分可达核心。
- 新增 `corona.recovery` 和启动接线：根据持久操作阶段选择目标或上一 revision，避免崩溃重启重复启动核心；待确认的 startup recovery 在实际 supervisor 状态到位后终结操作。
- 新增认证的 Nucleus 管理 API：旧扁平配置键兼容 `PUT /api/v1/config`，revision If-Match 与 Idempotency-Key；apply/restart/start/stop 接受操作并返回 operation ID；状态、schema、provider、platform/OneBot 设置和操作 snapshot/SSE 使用统一控制面。密钥字段只显示是否配置，不返回明文。
- 默认启动入口仍为 legacy，CN11 才切换。测试中发现 supervisor 新代启动时 snapshot 沿用旧 revision ID；已修正 `_run` 在启动态同步快照 revision，并由真实子进程 apply 成功/失败两条路径覆盖。

## 验收与验证

| 命令 / 检查 | 结果 |
| --- | --- |
| Corona 配置/事务/操作/API/恢复及 Nucleus snapshot 聚焦回归 | `.venv/bin/python -m pytest tests/corona tests/nucleus/test_snapshot_driver.py -q`：**40 passed / 6.43s**。包括 CAS/幂等、继承删除、外部编辑冲突、PREPARED/replace 硬退出后重启恢复、应用单活动锁、失败单次回滚、API redaction/冲突和真实 fake-core 子进程成功/目标启动失败两条路径。 |
| `.venv/bin/ruff check corona stella_bootstrap tests/corona` | 通过。 |
| `.venv/bin/python -m compileall -q corona stella_bootstrap` | 通过。 |
| `.venv/bin/python scripts/generate_message_flow.py --check` | 通过；`message-flow.982a65f5aef2.json` 匹配。 |
| `.venv/bin/python scripts/check_docs.py` | **119 files / 1,280 local links / 577 anchors / 0 errors**（本报告写入前；最终状态更新后复跑）。 |
| 完整 Python suite（隔离 `$STELLA_HOME=/tmp/stella-cn05-full-pzQE5n`，预建 `memory/`） | **4072 passed / 29 skipped / 4 failed / 1 warning / 251.38s**，NOT GREEN。失败：`test_subprocess_ack_pauses_claim_then_allows_fake_task_once`、`test_identity_mismatch_returns_no_input_not_other_bot`、`test_custom_endpoint_wire_api_chat_rejected`、`test_usage_today_shape`。四个精确节点在新隔离 home 单独重跑均通过（**4 passed / 6.03s**）；全量执行顺序/共享状态根因未知，不能据单测通过宣称全量通过。 |
| 使用边界 | 测试前 `STELLA_HOME` 未设置；全量及聚焦套件使用 pytest 临时目录和显式 `/tmp` 隔离 home，没有读取或改写用户配置、聊天或生产库；未启动真实模型、Bot、QQ/WebChat 或部署服务。Windows/macOS/BSD clean VM、Docker、产品启动/升级、live model/platform 与 release 仍 NOT READY。 |
| staged GitNexus `detect-changes --scope all --repo Stella_project --limit 1000` | **17 files / 17 symbols / 13 affected processes / HIGH**。 |
| staged GitNexus `detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | **182 files / 720 symbols / 88 affected processes / CRITICAL**（CN00–CN05 累计）。 |
| GitNexus 输出完整性 | `all` 与 `compare` 分开串行运行；两次均无 PARTIAL/truncated 标记。symbol/flow 列表有显示上限，但总数与 risk 已完整报告。 |
| `git diff --cached --check` | 通过。 |

## 下一阶段

CN06：迁移并归属全部 WebUI 路由与服务，Corona 代理业务输出，业务数据库访问继续只在 Nucleus。先完成最终 staged 图门禁和本包提交，再从新 HEAD 开始。默认入口仍保留 legacy。
