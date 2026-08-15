# 打印的napcat日志（隐藏部分真实信息，三段相同故仅保留第一段）

==== 2026-08-15 13:05:41 启动 NapCat =====
argv[0]:E:\stella\NapCat.Shell\NapCatWinBootMain.exe
argv[1]:D:\Program Files\Tencent\QQNT\QQ.exe
argv[2]:E:\stella\NapCat.Shell\NapCatWinBootHook.dll
Boot Command:"D:\Program Files\Tencent\QQNT\QQ.exe" --enable-logging
[NapCat Backend] Main Process ID:25568
Creating pipe: \\.\pipe\NapCat_25568
[NapCat Backend] Process resumed
config_current_version:9.9.33-51802

config_prev_version:

load from:D:\Program Files\Tencent\QQNT\versions\9.9.33-51802\QQNT.dll

NapCat Shell App Loading...
08-15 13:05:42 [[32minfo[39m] [QQ版本兼容性检测] 当前版本Appid未内置 通过Major获取 为了更好的性能请尝试更新NapCat

08-15 13:05:42 [[32minfo[39m] [PacketHandler] 加载成功

08-15 13:05:42 [[32minfo[39m] [Napi2NativeLoader] 加载成功

08-15 13:05:42 [[32minfo[39m] [FFmpeg] 检查 Native Addon 可用性...

08-15 13:05:43 [[32minfo[39m] [FFmpeg] ✓ 使用 Native Addon 适配器

08-15 13:05:43 [[33mwarn[39m] NativePacketClient: 未找到对应版本的偏移数据: 9.9.33-51802-x64

08-15 13:05:43 [[32minfo[39m] [NapCat] [Core] NapCat.Core Version: 4.18.15

08-15 13:05:43 [[32minfo[39m] [NapCat] [WebUi] WebUi Token: 【隐藏token】

08-15 13:05:43 [[32minfo[39m] [NapCat] [WebUi] WebUi User Panel Url: http://127.0.0.1:6099/webui?token=【隐藏token】

08-15 13:05:43 [[32minfo[39m] [NapCat] [WebUi] WebUi User Panel Url: http://[::]:6099/webui?token=【隐藏token】

08-15 13:05:43 [[32minfo[39m] 等待网络连接...

08-15 13:05:44 [[32minfo[39m] 网络已连接

08-15 13:05:44 [[32minfo[39m] 没有 -q 指令指定快速登录，将尝试配置账号或最近登录账号

08-15 13:05:44 [[32minfo[39m] 可用于快速登录 of QQ：
1. 【QQ ID#1】
2. 【QQ ID#2】 。

[NapCat] [WebUi] 检测到 NAPCAT_QUICK_PASSWORD，已在内存中计算 MD5 用于回退登录
08-15 13:05:44 [[32minfo[39m] 正在快速登录  【QQ ID#2】

[NapCat] [WebUi] 自动快速登录失败: 登录态已失效，请重新登录。
08-15 13:05:44 [[32minfo[39m] 正在密码登录  【QQ ID#2】

08-15 13:05:44 [[33mwarn[39m] 请扫描下面的二维码，然后在手Q上授权登录：

08-15 13:05:44 [[33mwarn[39m] 

二维码解码URL: 【隐藏】
如果控制台二维码无法扫码，可以复制解码url到二维码生成网站生成二维码再扫码，也可以打开下方的二维码路径图片进行扫码。

08-15 13:05:44 [[33mwarn[39m] 二维码已保存到 E:\stella\NapCat.Shell\cache\qrcode.png

08-15 13:05:44 [[32minfo[39m] 需要验证码, proofWaterUrl:  【隐藏】【QQ ID#2】

[NapCat] [WebUi] 自动密码回退登录需要验证码，请在登录页面继续完成: 【QQ ID#2】
08-15 13:07:44 [[31merror[39m] [Core] [Login] Login Error,ErrType:  1  ErrCode: 3

08-15 13:07:44 [[33mwarn[39m] 请扫描下面的二维码，然后在手Q上授权登录：

08-15 13:07:44 [[33mwarn[39m] 

二维码解码URL: 【隐藏】
如果控制台二维码无法扫码，可以复制解码url到二维码生成网站生成二维码再扫码，也可以打开下方的二维码路径图片进行扫码。

08-15 13:07:44 [[33mwarn[39m] 二维码已保存到 E:\stella\NapCat.Shell\cache\qrcode.png

08-15 13:09:47 [[31merror[39m] [Core] [Login] Login Error,ErrType:  1  ErrCode: 3

08-15 13:09:47 [[33mwarn[39m] 请扫描下面的二维码，然后在手Q上授权登录：

08-15 13:09:47 [[33mwarn[39m] 

二维码解码URL:【隐藏】
如果控制台二维码无法扫码，可以复制解码url到二维码生成网站生成二维码再扫码，也可以打开下方的二维码路径图片进行扫码。

08-15 13:09:47 [[33mwarn[39m] 二维码已保存到 E:\stella\NapCat.Shell\cache\qrcode.png

Press any key to continue . . . 
===== 2026-08-15 13:10:43 启动 NapCat =====
......
===== 2026-08-15 13:18:42 启动 NapCat =====
......

# bot本体日志
(stella) PS E:\stella\stella_project> python .\bot.py                                                                                    
08-15 13:05:40 [SUCCESS] nonebot | NoneBot is initializing...
08-15 13:05:40 [INFO] nonebot | Current Env: dev
08-15 13:05:40 [SUCCESS] nonebot | Succeeded to load plugin "single_session" from "nonebot.plugins.single_session"
08-15 13:05:40 [SUCCESS] nonebot | Succeeded to load plugin "echo" from "nonebot.plugins.echo"
08-15 13:05:40 [SUCCESS] nonebot | Succeeded to load plugin "nonebot_plugin_apscheduler"
08-15 13:05:40 [SUCCESS] bot_main | ✅ 加载系统提示词 (758 字符)
08-15 13:05:40 [INFO] extensions | [扩展: napcat_manager] 外部管理已就绪: E:\stella\NapCat.Shell
08-15 13:05:40 [SUCCESS] extensions | ✅ [扩展] napcat_manager 已加载
08-15 13:05:40 [INFO] bot_main | 🧹 [消息清理] 距上次清理超过 24h，启动时补执行
08-15 13:05:40 [SUCCESS] nonebot | Succeeded to load plugin "bot_main" from "stella_project.plugins.bot_main"
08-15 13:05:40 [SUCCESS] nonebot | Running NoneBot...
08-15 13:05:40 [SUCCESS] nonebot | Loaded adapters: OneBot V11
08-15 13:05:41 [INFO] uvicorn | Started server process [6688]
08-15 13:05:41 [INFO] uvicorn | Waiting for application startup.
08-15 13:05:41 [INFO] nonebot_plugin_apscheduler | Scheduler Started
08-15 13:05:41 [INFO] extensions | [NapCat] 已同步登录变量到 E:\stella\NapCat.Shell\config\.env
08-15 13:05:41 [INFO] extensions | [NapCat] 已通过 launcher-user.bat 外部启动（输出见 E:\stella\stella_project\napcat_launch.log）
08-15 13:05:41 [SUCCESS] extensions | [NapCat] 已通过 launcher-user.bat 自动拉起 NapCat.Shell
08-15 13:05:41 [INFO] uvicorn | Application startup complete.
08-15 13:05:41 [INFO] uvicorn | Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
08-15 13:10:40 [WARNING] extensions | [Watchdog] 心跳超时且主动探活失败（There are no bots to get.），准备外部重启 ...
08-15 13:10:40 [WARNING] extensions | [Watchdog] 第 1/3 次外部重启
08-15 13:10:40 [WARNING] extensions | [NapCat] 触发外部重启 NapCat.Shell ...
08-15 13:10:40 [INFO] extensions | [NapCat] 已外部终止 NapCat 进程树: [416]
08-15 13:10:43 [INFO] extensions | [NapCat] 已同步登录变量到 E:\stella\NapCat.Shell\config\.env
08-15 13:10:43 [INFO] extensions | [NapCat] 已通过 launcher-user.bat 外部启动（输出见 E:\stella\stella_project\napcat_launch.log）
08-15 13:10:44 [INFO] extensions | [NapCat] 重启后进程已确认存活
08-15 13:18:40 [WARNING] extensions | [Watchdog] 心跳超时且主动探活失败（There are no bots to get.），准备外部重启 ...
08-15 13:18:40 [WARNING] extensions | [Watchdog] 第 2/3 次外部重启
08-15 13:18:40 [WARNING] extensions | [NapCat] 触发外部重启 NapCat.Shell ...
08-15 13:18:40 [INFO] extensions | [NapCat] 已外部终止 NapCat 进程树: [7280]
08-15 13:18:42 [INFO] extensions | [NapCat] 已同步登录变量到 E:\stella\NapCat.Shell\config\.env
08-15 13:18:42 [INFO] extensions | [NapCat] 已通过 launcher-user.bat 外部启动（输出见 E:\stella\stella_project\napcat_launch.log）
08-15 13:18:44 [INFO] extensions | [NapCat] 重启后进程已确认存活
08-15 13:26:40 [WARNING] extensions | [Watchdog] 心跳超时且主动探活失败（There are no bots to get.），准备外部重启 ...
08-15 13:26:40 [WARNING] extensions | [Watchdog] 第 3/3 次外部重启
08-15 13:26:40 [WARNING] extensions | [NapCat] 触发外部重启 NapCat.Shell ...
08-15 13:26:40 [INFO] extensions | [NapCat] 已外部终止 NapCat 进程树: [22004]
08-15 13:26:42 [INFO] extensions | [NapCat] 已同步登录变量到 E:\stella\NapCat.Shell\config\.env
08-15 13:26:42 [INFO] extensions | [NapCat] 已通过 launcher-user.bat 外部启动（输出见 E:\stella\stella_project\napcat_launch.log）
08-15 13:26:44 [INFO] extensions | [NapCat] 重启后进程已确认存活
08-15 13:34:40 [WARNING] extensions | [Watchdog] 心跳超时且主动探活失败（There are no bots to get.），准备外部重启 ...
08-15 13:34:40 [ERROR] extensions | [Watchdog] 连续 3 次重启仍未恢复，停止自动重启。请人工检查 QQ 登录状态（可能已退化为扫码或触发风控）
08-15 13:40:40 [WARNING] extensions | [Watchdog] 心跳超时且主动探活失败（There are no bots to get.），准备外部重启 ...
08-15 13:40:40 [ERROR] extensions | [Watchdog] 连续 3 次重启仍未恢复，停止自动重启。请人工检查 QQ 登录状态（可能已退化为扫码或触发风控）
08-15 13:40:44 [INFO] uvicorn | Shutting down
08-15 13:40:44 [INFO] uvicorn | Waiting for application shutdown.
08-15 13:40:44 [INFO] nonebot_plugin_apscheduler | Scheduler Shutdown
08-15 13:40:44 [INFO] uvicorn | Application shutdown complete.
08-15 13:40:44 [INFO] uvicorn | Finished server process [6688]