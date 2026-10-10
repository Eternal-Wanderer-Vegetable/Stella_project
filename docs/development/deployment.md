# 部署工具

中文 | [English](deployment.en.md) · [文档总览](../README.md)

`deploy/` 是「检查逻辑全在 Python 侧、GUI 只是渲染器」的部署工具：doctor 输出结构化 JSON，
桌面安装器（Tauri）调用它并渲染，`stellacli` 也把它作为本地模式的领域后端；换 GUI 框架不用重写逻辑。当前子命令如下：

| 命令 | 用途 |
|---|---|
| `python -m deploy doctor [--json]` | 环境自检；`--json` 输出结构化结果（id/level/title/detail/fix_hint），供 GUI 做图标与本地化映射 |
| `python -m deploy init [--answers PATH] [--force] [--dry-run]` | 交互式生成 `.env`（基于 `.env.example` 逐行替换，模型 ID 从 LM Studio 拉列表选编号）；`--answers` 复用上次的 `deploy.answers.toml`，换机器重装 / CI 冒烟 / GUI（`save_config`）复用同一份答案 |
| `python -m deploy start [--force] [--detach]` | 先跑 doctor，无阻塞问题（或 `--force`）后启动 `bot.py`；`--detach` 后台启动并写 PID 到 `logs/stella.pid`（GUI 用） |
| `python -m deploy status [--json]` | 通过状态接口优先判断进程是否存活，并汇总链路健康度、调度器排队、今日用量与能力清单；接口不可达时再用 PID 文件兜底，并读取最近 JSON 日志 |
| `python -m deploy stop` | 优雅停止：写停止哨兵 → 轮询等待 → 降级信号 → 硬杀兜底（见下）；Tauri 安装器与 `bot.py` 位于同一发布目录 |
| `python -m deploy config-schema --json` | 输出 `settings.py` 的配置 schema（分组、默认值、注释），GUI 的「高级选项」表单据此生成 |
| `python -m deploy migrate [--from 旧目录] [--dry-run] [--fresh-runtime]` | 从旧版本安装目录导入用户数据并升级数据库；只读旧目录，报告同时返回 Markdown 原文并写入当前 `STELLA_HOME/migration_report.md` |
| `python -m deploy space-merge --from a,b --to c [--dry-run]` | 合并共享空间（记忆 + 画像 + FTS + 账本），替代过去要用户手搓的一串 UPDATE |
| `python -m deploy plugin-check <插件目录> [--json]` | 按 [插件接入规范](../reference/plugin-spec.md) 校验一个插件目录：16 项检查，零 error 才算达标。**会 import 并实例化该插件**（与启动时做的事同类），输出里明说这一点 |
| `python -m deploy plugin-scaffold <插件目录> [--endpoint 槽] [--force] [--dry-run] [--measure]` | 给插件生成 `capability.toml.draft`（`reviewed = false`，`keywords` 留空、候选词只写在注释里），并当场用**真实 embedding** 打一份量化报告（同域原型分离度、每条 example 与本能力原型的余弦、负样本余量）。`--measure` 只重算报告、不调模型，供人审时复算。产物是草稿：`.draft` 后缀与 `reviewed = false` 两道闸门都拦着它，人审改名并置 `true` 之后才进路由。**同样会 import 并实例化该插件** |
| `python -m deploy capabilities [--json]` | 列出能力清单：哪些能被聊天自动触发、哪些不能及原因、各自来自哪一层、哪个 provider 正在退避。数据走状态接口（注册表是 Bot 进程内的单例）；Bot 没运行时退到直接读磁盘上的三层声明，那份数据回答不了「可不可路由」，渲染时会说明 |
| `python -m deploy paths [--env-file]` | 输出解析后的程序目录 / 用户数据目录等路径；`--env-file` 只打印 `STELLA_HOME/.env` 路径（`start.bat` 用） |
| `python -m deploy manifest [--write]` | 生成发布包清单 `.stella-manifest.json`（升级时据此判断用户是否改过自带文件），release CI 调用 |
| `python -m deploy upgrade <源目录> --version X.Y.Z [--rollback] [--checksum SHA]` | 版本化升级：校验升级源（可选 tree SHA-256）后**原子切换**程序版本；`--rollback` 把激活记录翻转到保留的上一版本树（双向，不需要源目录） |
| `python -m deploy bootstrap install --profile {...}` | 安装 profile 声明的组件与默认模型（`oneclick-python` / `oneclick-rust` / `standalone-python` / `standalone-rust`）；安装器装载与手工补救共用这一入口 |
| `python -m deploy mcp list\|test` | 列出已配置的 MCP server / 对单个 server 做连通冒烟 |
| `python -m deploy packages ...` | 组件包目录与运维：`catalog` / `verify` / `list` / `rollback` / `napcat-status` / `napcat-install` / `napcat-uninstall` / `import-model` |
| `python -m deploy runtime status` | 查看 / 校验 Runtime Contract（组件清单、endpoint、schema 版本与诊断字段） |

分层：`probe` 采集（有副作用）→ `checks` 判断（纯函数，测试重点）→ `report` 渲染。
检查函数的判据与 ai_gateway 的实际行为保持一致（例如人格文件缺失在代码里只是 warning，
doctor 也就报 warn），避免「明明能跑却提示 error」。

**每次改 `checks.py` 或 `report.py`，顺手重新导出一次 mock**（前端/安装器用真实结构预览，
避免结构与后端漂移）：

```bash
python -m deploy doctor --json > stella-installer/src/mock/doctor-clean.json
```

`doctor-mixed.json`（带 items 的场景）需要手工构造，保持字段结构与 `doctor-clean.json` 一致、
`summary.ok = total - error - warn` 自洽。

### 停止链路（哨兵优先）

1. **Windows 下 GUI 与 Bot 不共享控制台**：安装器用 `CREATE_NO_WINDOW(0x08000000)` 启动
   Bot，子进程根本没有控制台，`GenerateConsoleCtrlEvent` 发的 `CTRL_BREAK` 永远送不到
   （实测）。任何依赖控制台事件的停止方案在 GUI 场景必然失效——停止链路的唯一可靠入口是
   文件哨兵（`core/stop_signal.py`，默认路径项目根 `.stella-stop-request`）。
2. **哨兵文件的三方契约**：deploy 写（`deploy/process.py` 的 `stop()`）→ Bot 读并自杀
   （`ai_gateway.watch_stop_request()` 观察到后触发 uvicorn 优雅关闭）→ Bot 启动时先清残留
   （`_start_stop_watcher` 里最早执行）。三者缺一则要么停不了，要么一启动就自杀。
3. **deploy 侧等待 = grace + 缓冲**：Bot 侧 `_graceful_shutdown()` 最长等
   `SHUTDOWN_GRACE_SECONDS(30)`。deploy 的等待窗口必须严格大于它（`STOP_WAIT_BUFFER_SECONDS`，
   与 grace 成比例），否则会在 Bot 收尾的瞬间硬杀，白等一场。

设计取舍：不用 `POST /shutdown`——status_api 只读，加写接口就多一个无鉴权的写接口，
`HOST=0.0.0.0` 时就是局域网可触发的远程关机；哨兵靠文件系统权限天然只限本机用户。
哨兵文件是运行期产物，已加入 `.gitignore` 与 `release.yml` 的排除清单与敏感文件校验。

**前端契约**：`deploy doctor --json`、`deploy config-schema --json` 与 `deploy paths` 是 GUI 的
数据契约，改结构要 bump schema 的 `version` 字段并同步 `stella-installer/src/mock/`。
`deploy migrate` 返回的是 Markdown 报告原文（同一份内容也会写进当前 `STELLA_HOME/migration_report.md`，
只生成一次就不会两处不一致），GUI 直接以等宽文本渲染。

**GUI 不自己判断用户数据目录在哪**：`python::data_root()` 去问 `deploy paths`。判据只有
`config/home.py` 一份——两处各写一套会出现「一边读旧目录、一边写新目录」，症状是
「保存成功但没生效」。

**GUI 依赖的两处格式约定**：
- `config/spaces/*.toml` 由安装器写入的文件以 `# Managed by Stella installer` 开头，
  改写该头或格式会影响 GUI 的「是否由安装器管理」判断；
- `config/settings.py` 的章节注释（`# ---------- 标题 ----------`）决定配置分组，写新配置
  项时保持该格式，GUI 才能正确归类（`deploy config-schema --json` 是分组结果的唯一事实来源）。
