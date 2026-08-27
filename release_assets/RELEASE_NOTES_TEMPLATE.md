# Stella vX.Y.Z 发布说明

> 打 tag 前把本文件更新为本版本的内容，CI 会直接把它作为 Release Notes。

## 主要变化

- （在此填写本版本的主要变化，可从两个 tag 之间的 commit 提炼）

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
  Stella-vX.Y.Z-win64\   ← 程序（升级时整个换掉，可以放心删）
  StellaData\            ← 你的数据（升级时一动不动）
```

`StellaData\` 与版本文件夹是**平级**的，所以升级后清理旧的版本文件夹是安全的。
从旧版本升级上来的安装继续把数据留在安装目录内，行为与以前一致。
`python -m deploy paths` 可以查看当前解析到的位置。

## 下载

见本 Release 的资产：`Stella-vX.Y.Z-win64.zip`（解压后双击 `Stella.exe` 或 `start.bat`）。
