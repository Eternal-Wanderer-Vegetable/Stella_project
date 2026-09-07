# 跨平台 CLI 控制台（stellacli）方案 v1.0

> 状态：已评审（2026-09-07），Q1–Q4 已定；**阶段 A 已实施并通过双形态 E2E**（见 §10 实施记录）。
> 已定决策：二进制名 **`stellacli`**；**永久独立发包**，不进 Windows 主发布包——CLI 定位为**面向没有 WebView 的设备**的备选入口（GUI 的替代而非附属），独立验证、独立分发；其余按本文方案执行。
> 日期：2026-09-07
> 目标：为 Stella 提供一个 **Windows / Linux 一致体验的命令行控制台**，统一本地运行、Docker 部署、配置、诊断、日志与升级的操作入口。
> 原则：CLI 是**编排层与渲染层**，领域逻辑不离开 Python `deploy` 模块——GUI 与 CLI 共用同一套 `--json` 契约，绝不双实现。

---

## 0. 现状与动机

当前 Stella 的操作入口有四套，各覆盖一角：

| 入口 | 平台 | 覆盖 | 缺口 |
|---|---|---|---|
| Stella.exe（Tauri GUI） | Windows | 配置向导、doctor、运行状态、启停 | 无命令行形态；Linux 无 GUI |
| start/stop/doctor.bat | Windows | 运行时引导 + 启停 + 自检 | 纯 Windows；无状态/日志命令 |
| `python -m deploy ...` | 双平台 | 全部领域逻辑（doctor/init/start/stop/status/migrate/plugin-*/capabilities/manifest） | 是开发工具不是产品：要先装好 Python；输出朴素；不管 Docker |
| `docker compose` | 双平台 | Docker 形态生命周期 | 用户要记 compose 细节；状态/日志分散在多个命令里 |

**缺口**：Linux 本地运行没有一等入口；Docker 形态缺一个聚合状态/日志的统一视图；所有平台都缺「不用先装 Python 就能跑的诊断入口」。 stellacli 补这块。

## 1. 技术选型：Rust

用户要求「尽可能使用 Rust」。结论：**可行且合适**，理由分三层：

1. **框架成熟度**（用户的前提条件）：Rust CLI 生态是当前最成熟的一档——`clap` v4 是事实标准（ripgrep、cargo 自身都在用；声明式子命令/帮助生成/补全一应俱全），`serde_json`、`anyhow`、`anstream` 同样是久经考验的组合。不存在「没有成熟框架」的情形。
2. **项目已有先例**：Stella.exe 的 Rust 侧（`stella-installer/src-tauri/src/commands.rs`）就是「spawn `python -m deploy <cmd> --json` → 拿 JSON 渲染」的契约；`python.rs` 里还有运行时引导的 Rust 实现。CLI 沿用同一契约，架构上与 GUI 同构，团队工具链（cargo、windows runner 构建）现成。
3. **备选对比**：
   - Python（typer/rich）：单一事实源最自然，但分发不了单文件二进制——「先装 Python 才能 doctor」恰恰是要消除的问题；
   - Go：生态同样成熟，但项目已引入 Rust（Tauri），再引入第二种编译语言只会摊薄维护面。

**依赖清单（刻意保持小）**：`clap`（derive）、`serde`/`serde_json`、`anyhow`、`anstream`+`anstyle`（颜色自动降级，尊重 `NO_COLOR`/管道）。不引入 async 运行时、不引入 HTTP 客户端（见 §3 说明）。

## 2. 架构

```
                       ┌─────────────── stellacli（Rust 单文件二进制） ───────────────┐
                       │  模式检测 · 子命令路由 · JSON→彩色渲染 · 日志 tail · compose 编排 │
                       └──────┬───────────────────┬───────────────────┬──────────────┘
                              │ 本地模式            │ Docker 模式        │ 两种模式通用
              runtime/python.exe 或 python3   docker compose <...>    读 ./StellaData/logs
                │  （Windows 发布包）              │ docker exec curl
                ▼                                 ▼                    （挂载在宿主机上）
   python -m deploy <cmd> --json        容器内同样跑 deploy --json          │
   （领域逻辑单一事实源：doctor/init/        或读容器健康检查                  ▼
    stop 哨兵协议/migrate/plugin-*）                            logs/*.jsonl、boot_debug.log
```

三条铁律：

1. **领域逻辑只在 deploy 模块**。doctor 的探测项、init 向导（含从 LM Studio 拉模型列表）、stop 的「哨兵→信号→硬杀」四阶协议（`deploy/process.py`，Windows 无控制台子进程靠哨兵文件才能优雅停）、migrate 的路径清单——stellacli 一律 spawn `python -m deploy` 完成，自己只做渲染与编排。**重实现哨兵协议是明令禁止的**：那套 grace/缓冲/僵尸判断是在 Windows 上踩出来的，双实现必然漂移。
2. **结构化契约 = `--json`**。doctor/status/capabilities/plugin-check 的 JSON 输出已存在且被 GUI 消费；stellacli 是第二个消费者。字段语义以 deploy 为准，stellacli 只消费不定义。
3. **Docker 模式零 Python 依赖**。宿主机上有 docker + stellacli 二进制即可完成启停/状态/日志/升级；需要领域逻辑的命令通过 `docker compose run --rm stella python -m deploy ...` 在容器内执行（TTY 透传，交互向导同样可用）。

## 3. 命令面设计

`stellacli <子命令>`，全局参数 `--mode local|docker`（默认自动检测）、`--json`（凡有结构化输出的命令都支持，供脚本消费）。

| 子命令 | 本地模式实现 | Docker 模式实现 |
|---|---|---|
| `doctor` | spawn `deploy doctor --json` → 彩色分组渲染（✔ 通过 / ⚠ 告警 / ✘ 阻塞），阻塞项汇总置顶 | `docker compose run --rm stella python -m deploy doctor --json` → 同一套渲染 |
| `init [--answers P]` | 透传交互向导（继承 TTY） | `docker compose run --rm stella python -m deploy init`（同左） |
| `start` | `deploy start --detach`（写 PID 文件） | `docker compose up -d`（napcat 一并起） |
| `stop` | `deploy stop`（哨兵优雅停，**不重实现**） | `docker compose stop`（stop_grace_period=15s 已配好） |
| `restart` | stop + start 串联 | `docker compose restart` |
| `status` | `deploy status --json` → 单屏面板：PID/存活/链路健康/调度队列/今日 token/能力数/运行时长 | `docker compose ps` + `docker inspect` 健康态 + `docker exec stella curl 127.0.0.1:8080/stella/status` → 同一面板（状态接口只在容器回环可达，必须经 exec 取） |
| `logs [-f] [--boot\|--jsonl\|--thought]` | **原生**：tail `logs/`（docker 模式读 `./StellaData/logs/`，挂载在宿主机，同样原生）；jsonl 按日志级别着色 | 同左（日志文件在宿主机挂载目录，不需要 compose logs；`--compose` 参数可切 `docker compose logs`） |
| `upgrade` | 打印 Releases 下载指引（自更新见 §7 阶段 C） | `docker compose build/pull stella` + `pull napcat` + `up -d`（与部署文档流程一致） |
| `migrate` / `plugin check` / `plugin scaffold` / `capabilities` / `manifest` | 透传 deploy 对应子命令（含各自 --json/--dry-run 参数） | 经 `docker compose run --rm stella ...` 透传 |
| `compose <任意参数>` | ——（本地模式报错） | `docker compose <args>` 直通逃生舱：CLI 没包到的 compose 操作不用离开习惯入口 |
| `--version` | 自身版本 + 调 `deploy --version`？deploy 无此命令——阶段 A 只报自身版本，与 pyproject 版本对齐 | 同左 |

设计说明：

- **不需要 HTTP 客户端**：状态探活全部经 `deploy status`（本地）或 `docker exec curl`（容器），stellacli 自身不直连状态接口——少一个依赖，也绕开「HOST=0.0.0.0 时连谁」的边角问题。
- **logs 原生实现**是 CLI 少数「自带逻辑」的点：轮询式 tail（不引 inotify，跨平台零成本）、UTF-8 直读、`--boot` 看 `boot_debug.log`（排查插件加载的第一现场）。文件路径解析规则：优先 `StellaData/logs/`（docker 与分离布局），回落 `logs/`（旧布局），与 `config/home.py` 的布局判定保持一致。

## 4. 模式检测与解释器发现

**模式检测**（`--mode` > 环境变量 `STELLA_MODE` > 自动）：自动判据按序——

1. 当前目录存在 `docker-compose.yml` 且 `docker` 可执行 → **docker**；
2. 存在 `bot.py` 且能找到 Python 解释器 → **local**；
3. 都不满足 → 报错并给出两种形态各自的安装指引（带文档链接）。

**解释器发现**（仅本地模式，与 `python.rs` 的注释约定一致）：`runtime/python.exe`（Windows 发布包，优先）→ `python3` → `python` → Windows `py -3`。找不到时给出可执行的修复提示（含「用 Docker 形态可免装 Python」的出路）。**阶段 A 不做运行时下载**——Linux 本地用户自备 Python ≥3.10（写入文档），引导见 §7 阶段 B。

## 5. 渲染与终端 UX

- doctor：按 `deploy/report.py` 的结果结构分组渲染，阻塞项（`has_blocking`）红色置顶 + 修复指引；`--json` 原样透传（脚本可移植）。
- status 面板：单屏信息密度优先（对齐 GUI「运行状态」页的字段子集），接口不可达时明确区分「进程在但 HTTP 未就绪」与「未运行」——`deploy status --json` 已带 `pid_file_present`/`api_reachable` 两个判据，直接消费。
- Windows 终端：启用 VT 处理序列 + 输出代码页切 UTF-8（失败静默降级纯文本）；检测到重定向/`NO_COLOR` 时全部命令输出无 ANSI 纯文本，`--json` 永远可用。
- 退出码纪律：领域命令透传 deploy 的退出码（doctor 有阻塞=1）；编排错误（找不到 docker/compose 文件）用独立非零码，便于脚本区分「Bot 有问题」与「工具用错了」。

## 6. 发布与分发

- **代码位置**：仓库根 `cli/`（独立 Cargo 工程 `stellacli`（crate 与二进制同名）），与 `stella-installer/src-tauri` 并列互不依赖（共享的只有「deploy --json 契约」这条约定）。
- **构建目标**：`x86_64-pc-windows-msvc`（windows-latest）+ `x86_64-unknown-linux-musl`（静态链接，任何发行版可直接跑，容器里也能用）。
- **CI**：ci.yml 加一个 job——`cargo fmt --check` + `clippy -D warnings` + `cargo test`（ubuntu 即可，Windows 编译验证放 release 侧）。
- **发布**：release.yml 加 job 产出 `Stella-CLI-version-v{ver}-windows-amd64.zip` / `Stella-CLI-version-v{ver}-linux-amd64.tar.gz` 挂到 Release assets。**永久独立发包，不进 Windows 主发布包**（已定）：CLI 面向没有 WebView 的设备，是独立验证的备选形态，与主包解耦。版本一致性校验扩一条：Cargo.toml version 必须等于 tag/pyproject 版本。
- **AGPL-3.0**：二进制随仓库源码同许可分发，Release 页对应 tag 即源码要约，合规无额外动作。

## 7. 分阶段实施

| 阶段 | 内容 | 交付判据 |
|---|---|---|
| **A：核心控制台** | Cargo 骨架 + §3 全部命令（透传/编排/渲染/logs 原生 tail）+ 模式检测/解释器发现 + CI + Release assets | ✅ 已实施（2026-09-07）：docker 形态全生命周期 + 本地模式（Windows，连真实运行中的 Bot）E2E 通过；Linux 由 CI 与 musl 静态构建覆盖 |
| **B：Linux 本地引导** | `stellacli prepare`：跨平台运行时引导（Linux 用 python-build-standalone，Windows 复用嵌入式 Python 常量）；顺带把三份引导逻辑收敛为一（start.bat 与 GUI python.rs 的同步测试已提示这里是三副本），start.bat 改薄壳调 stellacli | 全新 Linux 机器上 `stellacli prepare && stellacli doctor` 全绿，全程无手工装 Python |
| **C：增强** | shell 补全（clap_complete）、`stellacli open`（WebUI/文档快捷指引）、基于 GitHub Releases API 的升级提示 | 按需 |

## 8. 风险与边界

| 风险 | 对策 |
|---|---|
| CLI 与 deploy 逻辑漂移 | 铁律 §2.1：stellacli 不写领域逻辑；渲染只吃 `--json` 契约；CI 里加一条「stellacli 帮助文本列出的子命令必须与 deploy `__main__.py` 支持的集合一致」的静态检查 |
| Windows 控制台坑（信号送不到、ANSI 不支持、代码页） | 信号问题天然规避（停机走 deploy 哨兵）；ANSI/代码页做运行时探测降级 |
| 重实现诱惑（尤其 stop/引导） | 评审纪律：任何「这个逻辑 Rust 里再写一份」的 PR 需要专门论证为什么不能透传 |
| musl 静态二进制的体积/兼容 | clap 全家桶裸二进制 ~3–5MB，可接受；musl 规避 glibc 版本地狱，值得 |
| Docker 模式依赖宿主机 docker CLI | 检测不到 docker 时给出安装指引 + 提示可切 `--mode local` |
| 与 GUI 的关系 | 互不替代：GUI 面向普通用户，CLI 面向服务器/终端用户；共用 deploy 契约，无耦合无冲突 |

## 9. 待决问题（2026-09-07 评审已定）

| # | 问题 | 结论 |
|---|---|---|
| Q1 | 二进制名（`stella.exe` 会与 GUI 的 `Stella.exe` 在 NTFS 大小写不敏感文件系统冲突） | **`stellacli`**，对齐功能命名 |
| Q2 | 是否进 Windows 主发布包 | **不进，永久独立发包**。CLI 定位为面向没有 WebView 的设备的备选方案，独立验证、独立分发 |
| Q3 | 阶段 B 的 Linux Python 发行源 | python-build-standalone 官方 GitHub Releases + 国内镜像回落（与 start.bat 的双源策略同构） |
| Q4 | status 面板字段 | 精简面板 + `--json` 全量 |

---

## 10. 阶段 A 实施记录（2026-09-07）

**交付**：`cli/`（Cargo 工程，~7 个模块，15 个单元测试）、ci.yml `cli` job
（fmt/clippy/test/帮助文本冒烟，并纳入 PR 结果门禁）、release.yml
`build-cli-linux`（musl 静态）+ `build-cli-windows`（msvc）双 job，
产物 `Stella-CLI-version-v{ver}-{linux,windows}-amd64` 独立 Release assets。
release 二进制约 1MB。

**E2E（全部通过）**：docker 形态（沙箱 compose）——init（容器内非交互向导）→
doctor（0 错误 / exit 0）→ start → status（容器健康 + 容器内接口聚合）→
logs --boot / logs（jsonl 级别着色）→ stop → compose ps；本地形态（Windows
仓库根，自动检测命中 runtime/python.exe）——status 对接真实运行中的 Bot
（链路健康/调度器/用量渲染正确）、doctor、status --json 透传。

**E2E 发现并修复的两个缺陷**：

1. **deploy doctor 全新安装误报（上游缺陷）**：`deploy/probe.py` 的
   `_probe_database` 在 DB 不存在时对**缺失的** `memory/` 目录做
   `os.access(W_OK)`，任何全新部署（docker 与 Windows 均中招，GUI 首跑同样）
   都报「数据库不可写」阻塞级错误。修复：探测前先按 Bot 首次写库的行为
   `mkdir -p` 建目录（建不出来时 os.access 的 False 才是真结论），补回归测试
   `test_probe_database_fresh_install_parent_missing`；影响分析 LOW
   （唯一上游是同模块 collect），137 个 deploy 测试通过。
2. **logs 目录解析想当然**：初版把 docker 挂载目录写死为 `./StellaData`，
   实际挂载源叫什么由用户的 compose 决定（E2E 沙箱用 `./data` 即翻车）。
   修复：docker 形态用 `docker compose config --format json` 取**已解析**的
   /data 挂载源（绝对路径），失败回落启发式；配 `extract_data_mount` 单测。

**遗留**：与 deploy 子命令集的完整对账检查（需装全套 Python 依赖）暂缓，
CI 先用帮助文本冒烟兜底（§8 风险条目已注明）；阶段 B（`stellacli prepare`
跨平台运行时引导）与阶段 C 未动。
