# Stella vX.Y.Z 发布说明

> 打 tag 前把本文件更新为本版本的内容（含把标题与占位版本号改成实际值），CI 会直接把它作为 Release Notes。

## 主要变化

<!-- 安装与升级语义（随安装可靠性工程落地逐条核对删留） -->
- 安装/升级/卸载语义：升级保留旧版本树（可用 `python -m deploy upgrade
  --rollback` 一键回滚，重启生效）；卸载默认保留全部用户数据（记忆/配置/
  QQ 登录态），位置见 `%LOCALAPPDATA%\Stella\home.txt` 指针；升级与卸载
  全程留痕（`%LOCALAPPDATA%\Stella\*.journal`）。
- 新装默认数据根在 `%LOCALAPPDATA%\Stella\Data`（安装目录外，升级/卸载
  不再波及）；便携目录与旧布局优先级不变。
- 关于「未知发布者」提示：若本版本仍未代码签名，请在发布说明中保留这条声明——
  SmartScreen 的「未知发布者」警告属预期；每个 Release 附带 `SHA256SUMS.txt`
  供校验下载完整性。签名证书就绪并恢复强制签名门禁后，删除本条。
- 安装验收（干净 VM）报告随发布归档；体积门禁与实测基线见
  `release_assets/toolchain.json`。

- 发布线拆分为 OneClick-Python、OneClick-Rust、Standalone-Python 和
  Standalone-Rust，避免不同目标用户下载到不匹配的内容。
- OneClick 默认安装 `qwen3-embedding-0.6b`；聊天、整理和 reranker 模型不预装。
- OneClick 使用单个 Windows 安装程序；Standalone 仅包含 Stella 本体。
- OneClick Offline 离线安装程序（`Stella-OneClick-*-Offline-*`）：运行时、依赖、
  组件、模型与渲染内核全部随包内置，安装期零联网（体积约 1GB）。
- WebView2 运行时离线安装器已内嵌进全部 OneClick 安装程序：没有 WebView2 的
  电脑不再需要联网下载即可正常启动界面。

- Runtime Contract、统一组件状态、脱敏错误和实例级 Runtime 文件。
- Rust `runtime-manager` 契约基础层，并保留 Python deploy、CLI、Tauri 的兼容入口。
- AI 改为可选能力：支持可选的 Docker `llama` profile，llama 不可用时 Stella 基础功能继续运行。
- OneBot/NapCat 配置、可达性、断线和等待重连诊断，不会因 NapCat 断线误停 Stella。
- 组件/模型包 catalog、SHA-256 校验、原子模型导入、active model 回滚记录。

<!-- 按本版本实际变化增删：上面是长期有效的基线描述，新增特性写在这里。 -->

## 破坏性变更

> 必须列明。**但「让用户丢数据」不能再作为一种升级方式**：schema 每 +1 都必须带
> 自动迁移（见 `docs/development.md` 的规矩），所以这一节里不应再出现「请归档旧库」。

- 废弃全部 `NAPCAT_*` 配置（`NAPCAT_QQ_ACCOUNT` / `NAPCAT_QQ_PASSWORD` /
  `NAPCAT_SHELL_PATH` / `NAPCAT_AUTO_START` 等）：启动流程已与 NapCat 完全分离。
  升级时这些键会被 `.env` 合并器自动移除并在报告里列出，无需手工处理

<!-- 按本版本实际的破坏性变更增删。 -->

## 升级步骤

1. 运行 `stop.bat` 停止程序
2. OneClick：直接运行新版本的安装程序；Standalone：把新版本解压到一个新目录
3. 双击 `Stella.exe`（或 `start.bat`）→ 确认「配置导入」

配置、记忆、人格、空间设置与已装插件会自动搬过来，数据库自动升级，`runtime/` 自动复用。
全程只读旧目录，失败可原地重试；导入报告写在 `migration_report.md`。

命令行等价操作：

```bash
python -m deploy migrate --dry-run   # 先看预览（会在数据库副本上真跑一遍）
python -m deploy migrate             # 执行
```

## 数据目录

数据根位置取决于产品线与安装历史（`python -m deploy paths` 可查看实际位置与命中的规则）：

- **OneClick 全新安装**：数据根在程序目录之外的 `%LOCALAPPDATA%\Stella\Data`，
  由机器级指针 `%LOCALAPPDATA%\Stella\home.txt` 接入——升级换程序目录、卸载重装都不会波及数据；
  已有数据根一律沿用，绝不迁移。
- **Standalone 与手工部署**：默认在程序目录**同级**的 `StellaData/`（升级时不会被覆盖）：

```text
D:\你的目录\
  Stella\                ← 程序（升级时整个换掉，可以放心删）
  StellaData\            ← 你的数据（升级时一动不动）
```

- **便携模式（通用）**：在程序目录里手工建一个 `StellaData\` 子目录，程序会优先用它。

`StellaData\` 与版本文件夹是**平级**的，所以升级后清理旧的版本文件夹是安全的。
`python -m deploy paths` 可以查看当前解析到的位置。

## 下载

见本 Release 的 Windows 资产：`Stella-OneClick-*` 安装程序（在线/离线两种）与
`Stella-Standalone-*` 压缩包，另有 `SHA256SUMS.txt` 供校验下载完整性。

## 本版本边界

OneClick 会自动获取并校验固定版本的 NapCat 包，但不会代替 QQ 登录；
QQ 登录仍需人工扫码。

<!-- 按本版本实际验收情况更新：已验收矩阵写结论，未验收的明确列出。 -->
