# 废弃 napcat_manager（2026-08-18）

**原因不是代码有缺陷，而是问题不在我们这一侧。** QQ 的登录风控会把自动登录退化为扫码（`bug_report/bug_report_2026_8_15#1.md` 实测：快速登录过期 → 密码登录被要求验证码 `ErrType:1 ErrCode:3` + proofWaterUrl 风控 → 退化扫码），无论环境变量配得多完整都无法绕过。

B 批的看门狗改动（启动日志落盘、主动探活、重启上限）当时全部正确生效——它们没能解决问题，是因为问题本身不可自动化。既然登录必须有人在场，管理 NapCat 进程的收益就消失了。

**现在的做法**：用户用 [NapCatQQ Desktop](https://github.com/NapNeko/NapCatQQ-Desktop)（官方，GPL-3.0）安装并登录 NapCat，Bot 只连接现成的 OneBot WS 端点。

**副作用是好的**：Bot 本体变成纯 Python + WS，跨平台障碍基本消失。

**保留的部分**：心跳判活 + 主动探活的判定逻辑移到 `extensions/link_monitor/`，只告警不重启。丢弃的是进程启停、重启计数与上限、`set_restart_impl` 注入点。

原代码归档在 `_deprecated/napcat_manager/`（gitignore）。
