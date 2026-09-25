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
;
; 实现注记：全程用 LogicLib（${If}/${EndIf}，编译为相对跳转）——
; 钩子经 Tauri 模板插入 Section 后，Goto/label 的解析在该上下文
; 不可靠（v5.1.1-rc 实测：could not resolve label）。

!include "LogicLib.nsh"

!macro NSIS_HOOK_POSTINSTALL
  ; 仅离线变体：嵌入负载以 offline/MANIFEST.json 为标志
  ${If} ${FileExists} "$INSTDIR\resources\stella\offline\MANIFEST.json"
    DetailPrint "正在装载运行时与组件（离线装载，可能需要数分钟）…"

    ; 定位 Python 运行时 zip（版本号随 python.rs 演进，通配符定位）
    FindFirst $0 $1 "$INSTDIR\resources\stella\offline\python-*-embed-amd64.zip"
    ${If} $1 == ""
      FindClose $0
      Abort "离线负载缺少 Python 运行时 zip，安装无法继续。"
    ${EndIf}
    DetailPrint "解压 Python 运行时…"
    SetOutPath "$INSTDIR\resources\stella\runtime"
    ; FindFirst 输出的文件名不含路径——必须拼回 offline 目录再交给 tar
    nsExec::ExecToLog '"$SYSDIR\tar.exe" -xf "$INSTDIR\resources\stella\offline\$1" -C "$INSTDIR\resources\stella\runtime"'
    Pop $0
    FindClose $0
    ${If} $0 != 0
      Abort "Python 运行时解压失败（退出码 $0）。请确认系统为 Windows 10 1803+ 且磁盘空间充足后重试。"
    ${EndIf}

    ; 装载收尾（._pth 补丁 / pip 离线引导 / 依赖闭包 / 组件装载）——
    ; 逻辑与 GUI 的 prepare_runtime 同源（deploy.bootstrap），不重复实现
    DetailPrint "安装 Python 依赖与组件（NapCat / embedding 模型 / llama 后端）…"
    nsExec::ExecToLog '"$INSTDIR\resources\stella\runtime\python.exe" "$INSTDIR\resources\stella\deploy\nsis_bootstrap_helper.py" "$INSTDIR\resources\stella"'
    Pop $0
    ${If} $0 != 0
      Abort "组件装载失败（退出码 $0）：NapCat / embedding 模型可能未就绪。"
    ${EndIf}

    DetailPrint "装载完成。"
  ${EndIf}
!macroend
