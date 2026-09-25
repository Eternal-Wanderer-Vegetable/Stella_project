; OneClick 离线装载钩子（2026-09-25 用户方案）
; ---------------------------------------------------------------
; NSIS 解压完成后，立即在**安装阶段**完成全部装载：
;   Python 运行时解压 → ._pth 补丁 → pip 离线引导 → 依赖闭包安装 →
;   组件装载（NapCat / embedding 模型 / llama.cpp 后端，读 offline/packages）。
; GUI 首启因此只剩配置向导与秒级启动——不再有「后端未运行」与假卡死。
;
; 在线变体（安装树无 offline/MANIFEST.json）自动跳过：保持 GUI 内引导
; 下载的原流程。装载失败 → Abort 并给出中文原因，绝不产出半装状态；
; 用户重跑安装器即可整体重试。

!macro NSIS_HOOK_POSTINSTALL
  ; —— 仅离线变体：嵌入负载以 offline/MANIFEST.json 为标志 ——
  IfFileExists "$INSTDIR\resources\stella\offline\MANIFEST.json" stella_offline_found stella_skip_bootstrap

  DetailPrint "正在装载运行时与组件（离线装载，可能需要数分钟）…"

  ; 定位 Python 运行时 zip（版本号随 python.rs 演进，用通配符定位）
  FindFirst $0 $1 "$INSTDIR\resources\stella\offline\python-*-embed-amd64.zip"
  FindClose $0
  StrCmp $1 "" stella_no_python_zip

  ; 解压到 runtime\（Win10 1803+ 自带 bsdtar，可直接解 zip）
  SetOutPath "$INSTDIR\resources\stella\runtime"
  nsExec::ExecToLog '"$SYSDIR\tar.exe" -xf "$1" -C "$INSTDIR\resources\stella\runtime"'
  Pop $0
  IntCmp $0 0 stella_runtime_ok stella_runtime_fail stella_runtime_fail
  stella_runtime_fail:
    Abort "Python 运行时解压失败（退出码 $0）。请确认系统为 Windows 10 1803+ 且磁盘空间充足后重试。"
  stella_runtime_ok:

  ; 装载收尾（._pth 补丁 / pip 离线引导 / 依赖闭包 / 组件装载）——
  ; 逻辑与 GUI 的 prepare_runtime 同源（deploy.bootstrap），不重复实现
  nsExec::ExecToLog '"$INSTDIR\resources\stella\runtime\python.exe" "$INSTDIR\resources\stella\deploy\nsis_bootstrap_helper.py" "$INSTDIR\resources\stella"'
  Pop $0
  IntCmp $0 0 stella_helper_ok stella_helper_fail stella_helper_fail
  stella_helper_fail:
    Abort "组件装载失败（退出码 $0）：NapCat / embedding 模型可能未就绪。"
  stella_helper_ok:

  DetailPrint "装载完成。即将进入初始配置。"
  Goto stella_skip_bootstrap

  stella_no_python_zip:
    Abort "离线负载缺少 Python 运行时 zip，安装无法继续。"

  stella_skip_bootstrap:
!macroend
