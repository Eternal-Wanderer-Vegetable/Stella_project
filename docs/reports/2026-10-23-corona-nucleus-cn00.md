# Corona / Nucleus CN00 实施记录

日期：2026-10-23（Asia/Shanghai）。状态：**CN00 完成，CN01 待开始；CORONA-IMPL 仍 NOT READY。**

## 范围与图影响

实施分支为 `codex/corona-nucleus-implementation`，本包 GitNexus 绑定 `864c08f`。该提交归档了原工作区的计划与证据；CN00 未修改 `bot.py`、`config/settings.py`、deploy 或业务运行代码。

- `config/settings.py` upstream **CRITICAL**：278 个受影响符号、76 个直接依赖。该文件未改动。
- `bot.py` 为 **UNKNOWN / 0 图调用者**。源码引用审计确认 `entrypoint.sh`、`deploy/process.py`、`deploy/__main__.py` 启动它，桌面/安装器也以它作为项目根锚点；不把零图边视为无调用。
- `register_enabled_adapters` 为 LOW / 1 个直接调用者：`bot.py`。
- GitNexus 1.6.12 强制重建后绑定到 `864c08f`，状态 up-to-date。图包含 105,886 节点、264,173 边、1,126 clusters 与 814 条有界流程。分析仍省略大于 512 KiB 的 34 个文件，并报告 2,892 个入口候选、804 个 callee 分支、41 次 walk 预算和 21 条 trace 深度上限；另有跨语言字段边界。关键词索引首次失败后，经 `analyze --repair-fts` 失败、`analyze --force` 重建成功。上述限制不作为未调用证明。
- 暂存 CN00 交付物的 `detect-changes --scope all --repo Stella_project --limit 1000` 完整结果：9 files / 27 symbols / 0 affected processes / LOW。`detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000`：112 files / 141 symbols / 0 affected processes / LOW。一次并行 compare 因查询中断返回 PARTIAL，已丢弃并串行重跑；采纳的独立重跑没有 partial/truncated 标记。compare 范围包含本分支继承的阶段工作。

## 冻结合同

- **配置与框架：** 当前 CI 锁 `requirements-platform.lock` 固定 `nonebot2==2.5.0`，新回归只证明这一版本。NoneBot 2.5.0 的 `nonebot.init(_env_file=None)` 仍通过默认 `Env()` 读取工作目录 dotenv；实现层应在 `nucleus/framework.py` 集中使用 `Env(_env_file=None)`、`Config(_env_file=None, ...)`，并以版本门禁封装 `_resolve_combine_expr` 与全局 Driver 注册。不得把私有调用散布到模块，也不把 `init(None)` 当作禁用 dotenv。当前 `pyproject.toml` / `requirements.txt` 仍保留 `>=2.5.0`；未跑相同初始化合同的版本不获得 managed bridge 兼容声明。
- **路径：** Nucleus 保留 `PROJECT_ROOT` 为工作目录，`STELLA_HOME` 通过显式运行环境传递；插件和 `pyproject.toml` 相对路径据此解析。快照加载不得用全局 `chdir` 绕过 dotenv。
- **身份与操作：** 内部协议版本独立为 v1。身份含稳定 `instance_id`、`controller_boot_id`、`generation_id`、launch token、带创建身份的 PID、程序根、规范化数据根及配置 revision。接受管理操作即分配 `operation_id`；operation 持久快照记录阶段、目标/生效 revision、generation、终态、脱敏错误与是否恢复配置。沿用 `{status,message,data}` 响应 envelope；错误含稳定 `code`，不回显 secret 或原始异常栈。generation capability 仅经受保护启动通道传递，不放 URL/argv。
- **停止与锁：** 一个单调时钟 deadline 管完整排空。初始合同为优雅 45 秒、强停/reap 10 秒、宿主至少 65 秒，CN10 实测后校准。锁选择为进程句柄持有的 OS 文件区域锁：POSIX `fcntl.flock(LOCK_EX | LOCK_NB)`，Windows `msvcrt.locking(LK_NBLCK, 1)`；锁文件保持稳定，文件存在本身不代表持有锁。实例锁按 instance ID 隔离，写核心锁按**规范化实际 DB 路径**识别，不能只比较 `STELLA_HOME`。DB 路径登记与两平台行为验证由 CN03/CN10 完成。接口依据：[Python fcntl](https://docs.python.org/3.10/library/fcntl.html#fcntl.flock)、[Python msvcrt](https://docs.python.org/3.10/library/msvcrt.html#msvcrt.locking)。
- **恢复：** 配置 revision 的恢复与程序/数据库回退分开；任一旧写核心未确认退出或 DB 锁未释放时，不允许启动下一代。

## 验收证据

| 检查 | 结果 |
| --- | --- |
| 8 个既有生命周期、deploy 与 WebUI 基线文件；隔离 `STELLA_HOME` | **83 passed / 35.75s** |
| `tests/corona/test_config_source_snapshot.py`、`tests/nucleus/test_snapshot_driver.py` | **3 passed / 0.86s** |
| 新增测试 Ruff | 通过 |
| `verify_plan.py` 与当前源指纹/合同清单 | 12 个工作包；199 fingerprints；133 路由（21 control / 111 business / 1 split）；426 配置键；34 验收场景；30 归档链接与 77 个证据哈希通过 |
| adapter / 动态入口补查 | 默认 adapter 为 OneBot V11；`STELLA_ADAPTER_MODULES` 经 `parse_adapter_modules` / `register_enabled_adapters` 动态装配；WebUI route 与已审静态列表相符，未把候选数当作行为覆盖 |
| 配置源顺序 | 进程继承保持旧值 11；新进程读文件值 22；删除回落 90；外部环境覆盖为 44；`.env.prod` 覆盖为 33 |
| NoneBot Driver spike | 隔离子进程中先重现 `init(None)` 读取合成 cwd `.env`，再以显式无文件 `Env/Config` 建立真实 FastAPI Driver；快照端口 19001 保持稳定、cwd 不变，且无 Bot/server 启动 |
| 入口顺序合同 | 静态检查 token → 源码 Dashboard build / 失败退出 → legacy 接管 → `nonebot.init` → adapter/plugin → WebUI 的相对顺序；不启动真实 Bot |
| 用户数据边界 | STELLA_HOME 未沿用宿主配置；所有测试使用 `tmp_path` / 临时目录；未读取本机 `.env` 内容，未连接模型/QQ/WebChat，未打开生产数据库 |
| 文档链接门禁 | `python3 scripts/check_docs.py`：119 files / 1266 local links / 577 anchors / 0 errors；`git diff --check` 通过 |
| GitNexus pre-commit change detection | all: 9 files / 27 symbols / 0 processes / LOW; compare main: 112 files / 141 symbols / 0 processes / LOW. First parallel compare was PARTIAL and discarded; standalone rerun complete |

入口顺序回归是源码合同检查，不替代新架构的真实进程启动与关闭验收。Linux 上未实现 OS 锁；Windows 锁、故障恢复、完整 Python/Dashboard/Rust、平台 live、clean VM、Docker 与发布包均待后续工作包，产品仍 NOT READY。

## 下一步

进入 CN01：实现纯启动包和不可变配置 revision，覆盖所有 dotenv 正反例、未知插件键、权限、双 revision 隔离与 legacy 配置基线。CN02 前必须把本阶段 Driver spike 落入集中 framework adapter。
