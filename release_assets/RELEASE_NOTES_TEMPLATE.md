# Stella v4.0.1 发布说明

> 打 tag 前把本文件更新为本版本的内容，CI 会直接把它作为 Release Notes。

## 主要变化

- 发布线拆分为 OneClick-Python、OneClick-Rust、Standalone-Python 和
  Standalone-Rust，避免不同目标用户下载到不匹配的内容。
- OneClick 默认安装 `qwen3-embedding-0.6b`；聊天、整理和 reranker 模型不预装。
- OneClick 使用单个 Windows 安装程序；Standalone 仅包含 Stella 本体。

- 增加 Runtime Contract、统一组件状态、脱敏错误和实例级 Runtime 文件。
- 增加 Rust `runtime-manager` 契约基础层，并保留 Python deploy、CLI、Tauri 的兼容入口。
- AI 改为可选能力：支持可选的 Docker `llama` profile，llama 不可用时 Stella 基础功能继续运行。
- OneBot/NapCat 增加配置、可达性、断线和等待重连诊断，不会因 NapCat 断线误停 Stella。
- 增加组件/模型包 catalog、SHA-256 校验、原子模型导入、active model 回滚记录。

## 破坏性变更

> 必须列明。**但「让用户丢数据」不能再作为一种升级方式**：schema 每 +1 都必须带
> 自动迁移（见 `docs/development.md` 的规矩），所以这一节里不应再出现「请归档旧库」。

- 废弃全部 `NAPCAT_*` 配置（`NAPCAT_QQ_ACCOUNT` / `NAPCAT_QQ_PASSWORD` /
  `NAPCAT_SHELL_PATH` / `NAPCAT_AUTO_START` 等）：启动流程已与 NapCat 完全分离。
  升级时这些键会被 `.env` 合并器自动移除并在报告里列出，无需手工处理

## 升级步骤

1. 运行 `stop.bat` 停止程序
2. 把新版本解压到一个新目录
3. 双击 `Stella.exe`（或 `start.bat`）→ 确认「配置导入」

配置、记忆、人格、空间设置与已装插件会自动搬过来，数据库自动升级，`runtime/` 自动复用。
全程只读旧目录，失败可原地重试；导入报告写在 `migration_report.md`。

命令行等价操作：

```bash
python -m deploy migrate --dry-run   # 先看预览（会在数据库副本上真跑一遍）
python -m deploy migrate             # 执行
```

## 数据目录

全新安装会把用户数据放在程序目录**同级**的 `StellaData/`（升级时不会被覆盖）：

```text
D:\你的目录\
  Stella-v4.0.1\         ← 程序（升级时整个换掉，可以放心删）
  StellaData\            ← 你的数据（升级时一动不动）
```

`StellaData\` 与版本文件夹是**平级**的，所以升级后清理旧的版本文件夹是安全的。
从旧版本升级上来的安装继续把数据留在安装目录内，行为与以前一致。
`python -m deploy paths` 可以查看当前解析到的位置。

## 下载

见本 Release 的四类 Windows 资产：`Stella-OneClick-*` 安装程序与
`Stella-Standalone-*` 压缩包。v4.0.0 保留为历史 Pre-release，不被覆盖。

## 本版本边界

OneClick 会自动获取并校验固定版本的 NapCat 包，但不会代替 QQ 登录；
QQ 登录仍需人工扫码。真实 Windows 原生进程树、文件锁、端口冲突和升级回滚矩阵
仍需要在目标平台继续验收。

## 验证范围

契约级 Python/Rust 测试、Docker compose 配置和降级场景回归已纳入本版本验证。
当前环境未执行完整的真实 Windows 原生进程树、文件锁、升级回滚和 NapCat
自动化矩阵。
