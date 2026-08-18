# Stella vX.Y.Z 发布说明

> 打 tag 前把本文件更新为本版本的内容，CI 会直接把它作为 Release Notes。

## 主要变化

- （在此填写本版本的主要变化，可从两个 tag 之间的 commit 提炼）

## 破坏性变更

> 必须列明，否则从旧版升级的用户会遇到 v8 旧库告警却不知怎么办。

- 废弃全部 `NAPCAT_*` 配置（`NAPCAT_QQ_ACCOUNT` / `NAPCAT_QQ_PASSWORD` / `NAPCAT_SHELL_PATH` / `NAPCAT_AUTO_START` 等）：启动流程已与 NapCat 完全分离，残留配置会被 doctor 提示移除
- schema v8：记忆库改为按「共享空间」归属，旧库无法直接迁移。**升级前请先归档旧库**（把 `memory/agent_memory.db` 移走），让程序重建新库

## 升级步骤

1. 先运行 `stop.bat` 停止程序
2. 备份旧目录的 `.env` 与 `memory/agent_memory.db`
3. 把新版本解压到新目录，拷贝 `.env` 与记忆文件过去
4. 运行 `start.bat`

## 下载

见本 Release 的资产：`Stella-vX.Y.Z-win64.zip`（解压后双击 `start.bat`）。
