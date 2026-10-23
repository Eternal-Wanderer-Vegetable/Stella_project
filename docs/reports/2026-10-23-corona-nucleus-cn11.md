# Corona / Nucleus 实施 CN11：发布负载与默认切换门禁

日期：2026-10-23（Asia/Shanghai） · 基线：`28744fa`（CN10 证据绑定） · 分支：`codex/corona-nucleus-implementation`

范围：工程计划 [CN11](../plans/2026-10-23-corona-nucleus-engineering-plan.md#cn11)。本阶段完成发布包/installer staging 白名单、运行数据排除、Docker 存活探针与停止预算、双语部署/架构/发布说明，以及测试 home 隔离回归。默认入口保持 legacy；CN11 仍为 **NOT READY**，没有执行默认切换或发布。

## 交付

- `COMMON_DIRS` / `INSTALLER_DIRS` 纳入 `corona/`、`nucleus/`、`stella_bootstrap/`、`stella_contracts/`；保留版本匹配的 `webui/dist/`。Release zip 和 OneClick installer staging 均作实包检查。
- Release 与 Docker 上下文过滤 `.stella/` 控制状态、control-client/ownership、`.env` 变体和部署答案、SQLite 主库及 WAL/SHM/journal sidecar、日志、模型/NapCat 运行目录。隔离合成文件覆盖根与嵌套路径；`.env.example` 保留。
- Docker Healthcheck 先请求 Corona `/_corona/v1/health`，失败时回退 legacy `/stella/status`。文档说明 Corona liveness、Nucleus `core_phase` 与业务 readiness 的区别。Compose grace 从 15 秒升至 65 秒。
- 修复 suite-order auth 污染：每个 legacy WebUI 测试前后重置 Corona 全局 auth runtime override。
- 未修改业务 SQLite schema，未读取或写入现有生产数据。`bot.py` 与 Compose 默认仍启动 legacy。

## GitNexus 编辑前影响

- `COMMON_DIRS`、`FORBIDDEN_PARTS` 为 UNKNOWN/0；源码审计确认 Release 的 `INSTALLER_DIRS = COMMON_DIRS`，Standalone/OneClick 与 staging 均按这些目录迭代，禁用名单由 `_ignore_release_entries` / `_assert_clean` 消费。
- `build_standalone` LOW（2 impacted，直接 caller `main`）；`stage_installer_resources` LOW（2 impacted）；`_assert_clean` LOW（3 impacted）；`_ignore_release_entries` LOW（1 caller）。
- Dockerfile、compose 与 `.dockerignore` 图关系 UNKNOWN/0；源码审计确认镜像 `COPY` 使用根 Docker 上下文，compose 管理健康检查和停止时间。
- `tests/webui/conftest.py` UNKNOWN/0；pytest 配置发现 `tests/`，该 conftest 由 `tests/webui` 子树自动加载。新 fixture 只在 WebUI 测试之间清理进程级 auth override。
- 架构双语页 MEDIUM（53–57 个文档引用节点）；发布双语页 MEDIUM（56–69 个文档引用节点）。`progress.md` LOW/26、`session-handoff.md` LOW/19、`feature_list.json` LOW/19。影响均为文档引用关系，不是运行时调用者。没有 HIGH/CRITICAL 目标。

## 验证

- Cometa 与配置 WebUI 测试文件在新隔离 fixture 下：**43 passed / 5.59s**。
- 安装合同及发布资产 targeted tests：**60 passed / 1.01s**；完整 Python 回归随后在同一隔离 home 模式下通过。
- `.venv/bin/ruff check .` 与 `git diff --check` 通过。
- Standalone Python zip `Stella-Standalone-Python-v6.2.0-windows-amd64.zip`：561 members；Corona、Nucleus、bootstrap/contracts 四包及 `webui/dist/index.html` 全部存在；`scripts/check_release_archive.py` 通过，额外扫描 0 个禁用运行数据/秘密命中。
- OneClick installer staging：5/5 必需资产在场；`.env.example` 在场，禁用运行数据/秘密文件 0 个。
- Docker scratch build 使用 15 类合成数据标记：保留 `.env.example` 与两个程序入口，过滤 `.stella`、密钥、control/ownership、部署答案、SQLite sidecar、日志、models、NapCat；0 个禁用命中。
- Dashboard 三份目录 `dashboard/dist`、`webui/dist`、`desktop/dashboard-dist` 完全一致。Compose YAML 由 PyYAML 6.0.3 解析成功，确认 `init: true`、`stop_grace_period: 65s`。
- 真实 Docker 应用镜像构建未完成：Docker 29.1.3 client/server 可用，但拉取 `node:24-slim` 遇到 Docker Hub TLS handshake timeout。主机没有 `docker compose` 插件，故未运行 Compose config/up；scratch build 只验证上下文过滤。
- 隔离 `STELLA_HOME` 的全量 Python：**4115 passed / 29 skipped / 3 warnings / 281.94s**。此前 suite-order 的 Cometa/WebUI 401 失败在加入每例 auth runtime 清理后消失。机器可读原始摘要位于 [evidence](evidence/corona-nucleus-cn11/summary.json)；GitNexus 提交门禁会在证据提交中补齐。

## 未运行 / 未完成

Windows/Linux 干净 VM、六类最终产品冷启动/重启/失败恢复/升级/回退，真实 Docker 启动，真实 QQ/OneBot、WebChat 与模型验收均未运行。Rust 工具链不可用。legacy 回退前的树退出、数据锁释放和程序/schema 兼容证明仍未提供。

因此完成的是 CN11 的本地打包和容器配置准备，不满足默认切换条件。维持 `CORONA-IMPL` `in_progress` / **NOT READY**，legacy 保持默认；只有所有必需 VM、live、容器和回退证据齐全后再独立执行切换。
