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
!include "FileFunc.nsh"

; 预检查空间下限（GB）。这是**保守下限**而非精确峰值模型：压缩负载 +
; 展开树 + runtime + 组件 + 日志余量按当前产物实测 > 2GB；精确的逐卷
; 峰值估算（读 MANIFEST 尺寸动态计算）属于 S15 的完整矩阵， hooks 里
; 拿不到 JSON 解析能力，先用可解释的保守值挡住明显不够的目标卷。
!define STELLA_PREINSTALL_MIN_GB 3

!macro NSIS_HOOK_PREINSTALL
  ; S11a：升级开始留痕——journal 在 INSTDIR 之外，交互式升级的旧卸载器
  ; 删不到它。旧版本号读自注册表（读不到记 unknown）。
  ${If} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
    CreateDirectory "$LOCALAPPDATA\Stella"
    ReadRegStr $R7 SHCTX "${UNINSTKEY}" "DisplayVersion"
    ${If} $R7 == ""
      StrCpy $R7 "unknown"
    ${EndIf}
    FileOpen $R8 "$LOCALAPPDATA\Stella\upgrade-journal.txt" a
    ${If} $R8 != ""
      FileSeek $R8 END
      ${GetTime} "" "L" $0 $1 $2 $3 $4 $5 $6
      FileWrite $R8 "$2-$1-$0 $4:$5:$6 升级开始：$R7 -> ${VERSION}$\r$\n"
      FileClose $R8
    ${EndIf}
  ${EndIf}

  ; ---------- 预检查（WP08）：把昂贵步骤之前就能判定的问题挡在最前 ----------
  ; 注意：本钩子在 Tauri 文件释放之前运行，$INSTDIR 可能尚不存在。

  ; 1) 目标路径长度：程序树是「安装目录 + resources\stella + runtime 深层」，
  ;    INSTDIR 本身过长会让深层文件超出 MAX_PATH（未启用长路径策略的系统
  ;    上直接安装失败）。不默默改系统长路径策略，只提前解释。
  StrLen $2 "$INSTDIR"
  ${If} $2 > 120
    Abort "安装路径过长（$2 字符）：请选择更短的安装目录（建议 ≤120 字符），否则深层运行时文件可能超出 Windows 路径上限。"
  ${EndIf}

  ; 2) 目标卷可用空间（FileFunc 的 ${DriveSpace}，系统内置能力；
  ;    /D=F = free，/S=G = 以 GB 为单位——语义已对照本仓库构建所用
  ;    NSIS 的 FileFunc.nsh 源码核实）
  ${DriveSpace} "$INSTDIR" "/D=F /S=G" $3
  ${If} ${Errors}
    Abort "无法读取目标卷的可用空间：请检查安装位置后重试。"
  ${EndIf}
  ${If} $3 < ${STELLA_PREINSTALL_MIN_GB}
    Abort "目标卷可用空间不足（约 $3 GB，至少需要 ${STELLA_PREINSTALL_MIN_GB} GB）：程序、运行时、组件与日志都需要空间。请清理磁盘或更换安装位置。"
  ${EndIf}

  ; 3) 目标目录可写（预创建 + 探测目录 + 清理；只读目录/权限问题在此暴露，
  ;    而不是解压到一半失败留下半装状态）
  CreateDirectory "$INSTDIR"
  CreateDirectory "$INSTDIR\__stella_wtest"
  ${IfNot} ${FileExists} "$INSTDIR\__stella_wtest\*.*"
    Abort "安装目录不可写：请检查权限（或选择了只读位置）后重试。"
  ${EndIf}
  RMDir "$INSTDIR\__stella_wtest"
!macroend

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

  ; ---------- 版本化程序树（S11 Phase 2，双轨开关）----------
  ; 开关 = 随包 .stella-versioned-layout 标记（staging 在 CI 显式开启时
  ; 写入；旧包/关闭态没有它 → 本块整体跳过，现状布局逐字节不变）。
  ; 动作：把本次释放的程序文件**移动**到 $INSTDIR\app\<版本>\（同卷
  ; rename，快），复制随包 launcher 为稳定入口 $INSTDIR\Stella.exe，
  ; 再由嵌入式 Python（write-record 子命令）写机器级激活记录并做旧树
  ; GC。任何失败 → 尽力恢复现布局并继续——安装本身已成功，版本化只是
  ; 增强层，绝不因它把整次安装判失败。全程 LogicLib 嵌套（本上下文
  ; Goto/label 不可靠，见文件头注）。
  ${If} ${FileExists} "$INSTDIR\resources\stella\.stella-versioned-layout"
    DetailPrint "启用版本化程序树布局…"
    ClearErrors
    FileOpen $R5 "$INSTDIR\resources\stella\.stella-version" r
    ${If} $R5 != ""
      FileRead $R5 $R6
      FileClose $R5
      CreateDirectory "$INSTDIR\app"
      ${If} ${FileExists} "$INSTDIR\app\$R6\*.*"
        ; 同版本重装：以本次释放的新树替换 app 内同版本旧树
        RMDir /r "$INSTDIR\app\$R6"
      ${EndIf}
      Rename "$INSTDIR\resources" "$INSTDIR\app\$R6\resources"
      ${If} ${Errors}
        DetailPrint "程序树搬移失败，保持现状布局（安装仍可正常使用）。"
      ${Else}
        Rename "$INSTDIR\${MAINBINARYNAME}.exe" "$INSTDIR\app\$R6\${MAINBINARYNAME}.exe"
        ${If} ${Errors}
          ; 主程序搬移失败：把 resources 搬回去，回到现状布局
          Rename "$INSTDIR\app\$R6\resources" "$INSTDIR\resources"
          DetailPrint "主程序搬移失败，已恢复现状布局。"
        ${Else}
          CopyFiles /SILENT "$INSTDIR\app\$R6\resources\stella\launcher\StellaLauncher.exe" "$INSTDIR\${MAINBINARYNAME}.exe"
          DetailPrint "版本化布局就绪（版本 $R6）。"
          ; 激活记录 + 旧树 GC（Python 侧落盘；仅离线变体有嵌入式
          ; Python 可用。在线变体由 launcher 的枚举兜底覆盖，机器记录
          ; 的补写属于 Phase 2 后续）。
          ${If} ${FileExists} "$INSTDIR\app\$R6\resources\stella\runtime\python.exe"
            nsExec::ExecToLog '"$INSTDIR\app\$R6\resources\stella\runtime\python.exe" "$INSTDIR\app\$R6\resources\stella\deploy\nsis_bootstrap_helper.py" "$INSTDIR\app\$R6\resources\stella" write-record'
            Pop $2
          ${EndIf}
        ${EndIf}
      ${EndIf}
    ${Else}
      DetailPrint "缺少 .stella-version，跳过版本化布局。"
    ${EndIf}
  ${EndIf}
!macroend

; 卸载契约（S10b）：用户数据（记忆/配置/QQ 登录态/模型）在卸载时**默认
; 全部保留**——这本来就是按文件卸载的事实行为，这里把它变成显式语义
; 并留痕。journal 写在 INSTDIR 之外（$LOCALAPPDATA\Stella\），旧卸载器
; 与重装都碰不到它。已知限制：钩子只随新构建分发；从旧版本升级来的
; 安装在卸载时没有这些钩子（发布说明如实标注，不做假承诺）。
!macro NSIS_HOOK_PREUNINSTALL
  CreateDirectory "$LOCALAPPDATA\Stella"
  ${GetTime} "" "L" $0 $1 $2 $3 $4 $5 $6
  ${If} ${FileExists} "$LOCALAPPDATA\Stella\home.txt"
    FileOpen $R9 "$LOCALAPPDATA\Stella\uninstall-journal.txt" a
    ${If} $R9 != ""
      FileSeek $R9 END
      FileWrite $R9 "$2-$1-$0 $4:$5:$6 卸载：用户数据已保留（数据根见 home.txt 指针）$\r$\n"
      FileClose $R9
    ${EndIf}
    DetailPrint "用户数据已保留（数据根位置见 $LOCALAPPDATA\Stella\home.txt）。"
  ${Else}
    FileOpen $R9 "$LOCALAPPDATA\Stella\uninstall-journal.txt" a
    ${If} $R9 != ""
      FileSeek $R9 END
      FileWrite $R9 "$2-$1-$0 $4:$5:$6 卸载：未检测到外置数据根指针（旧版安装）——如数据在安装目录内，删除该目录前请自行备份。$\r$\n"
      FileClose $R9
    ${EndIf}
    DetailPrint "未检测到外置数据根指针：若数据在安装目录内，删除目录前请自行备份。"
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; 占位：运行期残留（runtime/、pip site-packages、.stella 缓存）的
  ; ownership 清单清理属于 S11 Phase 2（版本化程序树）——当前语义是
  ; 「卸载只删 NSIS 已知文件，其余保留并有 uninstall-journal 留痕」。
!macroend
