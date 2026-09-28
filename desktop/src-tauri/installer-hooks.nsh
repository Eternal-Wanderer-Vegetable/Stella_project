; OneClick 离线装载钩子（2026-09-25 用户方案；2026-09-28 安装可靠性加固）
; ---------------------------------------------------------------
; NSIS 解压完成后，立即在**安装阶段**完成全部装载：
;   Python 运行时 zip 校验 → 解压 → ._pth 补丁 → pip 离线引导 →
;   依赖闭包安装 → Rust wheel（如随包）→ 组件装载（NapCat / embedding
;   模型 / llama.cpp 后端，读 offline/packages）。
; GUI 首启因此只剩配置向导与秒级启动——不再有「后端未运行」与假卡死。
;
; 在线变体（负载模式声明为 online）不触发本钩子：保持 GUI 内引导下载
; 的原流程。装载失败 → Abort 并给出中文原因与退出码。
; 注意：NSIS 的 Abort 只停止安装器，不撤销已落盘的文件/pip 改动；
; 半装状态由 deploy.bootstrap 的进度记录如实落盘并在重试时复核。
;
; 实现注记：全程用 LogicLib（${If}/${EndIf}、${Do}/${Loop} 编译为相对
; 跳转）——钩子经 Tauri 模板插入 Section 后，Goto/label 的解析在该上
; 下文不可靠（v5.1.1-rc 实测：could not resolve label）。
;
; 寄存器纪律（2026-09-28 修 F07）：FindFirst 的句柄寄存器（$R0）绝不
; 被后续 nsExec 的 Pop 复用——旧实现用 $0 同时存句柄和退出码，
; FindClose 关掉的是被覆盖后的退出码值，句柄泄漏且校验形同虚设。

!include "LogicLib.nsh"

!macro NSIS_HOOK_POSTINSTALL
  ; 仅离线变体：嵌入负载以 offline/MANIFEST.json 为标志
  ${If} ${FileExists} "$INSTDIR\resources\stella\offline\MANIFEST.json"
    DetailPrint "正在装载运行时与组件（离线装载，可能需要数分钟）…"

    ; 1) 精确选取唯一的 Python 运行时 zip：通配符必须恰好命中一个——
    ;    0 个说明负载残缺，多于 1 个说明混入了旧版 zip，两者都必须
    ;    失败而不是解压「随便哪个」。
    FindFirst $R0 $1 "$INSTDIR\resources\stella\offline\python-*-embed-amd64.zip"
    ${If} $1 == ""
      FindClose $R0
      Abort "离线负载缺少 Python 运行时 zip，安装无法继续。"
    ${EndIf}
    StrCpy $R2 $1
    FindNext $R0 $1
    ${If} $1 != ""
      FindClose $R0
      Abort "离线负载包含多个 Python 运行时 zip（$R2 与 $1），安装包不完整。"
    ${EndIf}
    FindClose $R0

    ; 2) 解压前校验 zip 哈希（构建期把期望 SHA256 写进 python-zip.sha256，
    ;    无换行、恰好 64 位十六进制）。用系统自带的 certutil 哈希、find
    ;    匹配期望值：不依赖任何随包工具，Python 尚未就位也能校验自己。
    FileOpen $R3 "$INSTDIR\resources\stella\offline\python-zip.sha256" r
    ${If} $R3 == ""
      Abort "离线负载缺少 python-zip.sha256，无法在解压前校验运行时完整性。"
    ${EndIf}
    FileRead $R3 $R4
    FileClose $R3
    DetailPrint "正在校验 Python 运行时完整性…"
    nsExec::ExecToLog '"$SYSDIR\cmd.exe" /c certutil -hashfile "$INSTDIR\resources\stella\offline\$R2" SHA256 | find /i "$R4"'
    Pop $2
    ${If} $2 != 0
      Abort "Python 运行时校验失败（期望 SHA256 $R4）。安装包可能损坏，请重新获取。"
    ${EndIf}

    ; 3) 解压（$R0 句柄已关闭，$2 只存退出码——两者不再混用）
    DetailPrint "解压 Python 运行时…"
    SetOutPath "$INSTDIR\resources\stella\runtime"
    ; FindFirst 输出的文件名不含路径——必须拼回 offline 目录再交给 tar
    nsExec::ExecToLog '"$SYSDIR\tar.exe" -xf "$INSTDIR\resources\stella\offline\$R2" -C "$INSTDIR\resources\stella\runtime"'
    Pop $2
    ${If} $2 != 0
      Abort "Python 运行时解压失败（退出码 $2）。请确认系统为 Windows 10 1803+ 且磁盘空间充足后重试。"
    ${EndIf}

    ; 4) 装载收尾（._pth 补丁 / pip 离线引导 / 依赖闭包 / Rust wheel /
    ;    组件装载）——逻辑与 GUI 的 prepare_runtime 同源（deploy.bootstrap）
    DetailPrint "安装 Python 依赖与组件（NapCat / embedding 模型 / llama 后端）…"
    nsExec::ExecToLog '"$INSTDIR\resources\stella\runtime\python.exe" "$INSTDIR\resources\stella\deploy\nsis_bootstrap_helper.py" "$INSTDIR\resources\stella"'
    Pop $2
    ${If} $2 != 0
      Abort "组件装载失败（退出码 $2）：NapCat / embedding 模型可能未就绪。"
    ${EndIf}

    DetailPrint "装载完成。"
  ${EndIf}
!macroend
