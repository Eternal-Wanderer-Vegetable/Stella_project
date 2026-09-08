# 打包（用户在会话中报告，无 CI 日志）

## 现象 1：主安装包混入开发目录

`Stella-vx.x.x-win64.zip` 中包含大量与运行无关的内容：`.claude/`（AI 编码
代理技能）、`AGENTS.md`、`CLAUDE.md`、`cli/`（Rust CLI 源码）、`assets/`
（README 仓库渲染图）、`.gitattributes`、`.stella-state.json`（开发机的
运行痕迹，属 STELLA_HOME 产物，被历史误提交）。

根因：release.yml 的 rsync 排除清单是显式维护的（刻意不复用 .gitignore），
Phase 0~5 期间新跟踪的这些开发文件没有同步补进清单。

修复：补齐排除项，并把它们加进「发布前敏感/开发目录 grep 守卫」——排除
清单漏一项时守卫直接中止发布，两道锁同源维护。

## 现象 2：CLI 包单独下载启动报错

`Stella-CLI-version-v*-windows-amd64.zip` / `*-linux-amd64.tar.gz` 只含
stellacli 二进制，启动即报「未找到 Stella 项目根」。

根因：stellacli 是纯编排层（跨平台 CLI 控制台方案 §2）——`find_root()` 需要
含 bot.py 的目录，本地形态还要 Python（runtime/python.exe 或系统 Python）
透传 `python -m deploy`。只发二进制缺全部运行组件。

修复：重构 release.yml——CLI 二进制先行构建（两个独立作业产出 artifact），
`build` 作业组装三个包。CLI 包 = 完整程序目录 + stellacli，去掉 Tauri
安装器与 GUI 向导；Windows 版保留 start.bat（它就是嵌入式 Python 运行时
引导，stellacli 自动识别 runtime/python.exe），Linux 版去 .bat、配系统
Python 说明；新增 README-CLI-快速开始.txt 与包内完整性守卫（缺组件/
混入安装器即发布失败）。
