@echo off
REM 本文件为 GBK(CP936) 编码：cmd 解析器在 UTF-8+chcp 65001 下会随机错位
REM （部分多字节字符所在行被当成命令执行，输出一堆「is not recognized」）。
REM 目标用户均为中文 Windows，默认控制台代码页即 936，无需切 UTF-8。
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM Stella 启动器（唯一入口）：首次安装 + 后续启动。
REM 安全软件可能拦截「下载并运行 Python」，若安装卡住或被隔离，
REM 请把本目录加入杀软信任列表后重试。
REM ============================================================

REM ---------- 段 1：常量定义 ----------
REM PY_SHA256 取自 python.org 下载页的官方校验值，必须准确，写错会导致每次安装都失败。
REM 固定 3.12 系列。升级 patch 版本时需同步改 PY_VER 与 PY_SHA256；
REM 主次版本（3.12 → 3.13）变更时，python*._pth 已用通配符匹配，无需改动。
set PY_VER=3.12.10
set PY_ZIP=python-%PY_VER%-embed-amd64.zip
set PY_SHA256=4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3
set RUNTIME_DIR=runtime
set PY=%RUNTIME_DIR%\python.exe

REM ---------- 段 2：已安装则跳过下载/安装 ----------
if exist "%PY%" goto :run

echo 首次运行，正在准备 Python 运行环境（约 100MB）...

REM ---------- 段 3：下载 Python（官方 + 镜像，curl 与 PowerShell 各一轮，共四次机会） ----------
REM Windows 10 1803+ 自带 curl.exe，旧系统退化到 PowerShell。
REM 先官方后镜像：国内直连 python.org 常超时，但镜像可能滞后新版本。
call :try_download "https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%" "%PY_ZIP%"
if errorlevel 1 call :try_download "https://mirrors.huaweicloud.com/python/%PY_VER%/%PY_ZIP%" "%PY_ZIP%"
if errorlevel 1 call :try_download_ps "https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%" "%PY_ZIP%"
if errorlevel 1 call :try_download_ps "https://mirrors.huaweicloud.com/python/%PY_VER%/%PY_ZIP%" "%PY_ZIP%"
if errorlevel 1 (
    echo [错误] 四次下载尝试均失败，请检查网络后重试。
    pause
    exit /b 1
)

REM ---------- 段 4：校验 sha256 ----------
REM 截断的 zip 解压后会产生莫名其妙的 import 错误，排查成本极高，此步不能省。
for /f "skip=1 tokens=* delims=" %%h in ('certutil -hashfile "%PY_ZIP%" SHA256') do (
    set "HASH=%%h"
    goto :hash_done
)
:hash_done
set "HASH=!HASH: =!"
if /i not "!HASH!"=="%PY_SHA256%" (
    echo [错误] 下载文件校验失败，可能下载不完整或被篡改。
    echo   期望: %PY_SHA256%
    echo   实际: !HASH!
    echo 请删除 %PY_ZIP% 后重试。
    pause
    exit /b 1
)

REM ---------- 段 5：解压 ----------
echo 解压 Python 运行时...
powershell -NoProfile -Command "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%RUNTIME_DIR%' -Force"
if errorlevel 1 (
    echo [错误] 解压失败，请删除 %PY_ZIP% 后重试。
    pause
    exit /b 1
)

REM ---------- 段 6：启用 site-packages（嵌入式 Python 的关键坑） ----------
REM 嵌入式 Python 的 ._pth 有两处必改：
REM 1) 默认注释掉了 import site，不取消则 pip 装到 Lib\site-packages 的包 import 不到；
REM 2) ._pth 存在时 Python 只按该文件构建 sys.path（等价于带上 -E -s），
REM    且其中的相对路径是相对 python.exe 所在目录解析的——那个 "." 指向 runtime\
REM    而非项目根，因此 "runtime\python.exe -m deploy" 会报
REM    No module named deploy（2026-08-18 实测）。追加 ".." 把项目根加进 sys.path。
for %%f in ("%RUNTIME_DIR%\python*._pth") do (
    powershell -NoProfile -Command ^
      "$p='%%~f'; $c=Get-Content $p; $c = $c -replace '^#import site','import site'; if ($c -notcontains '..') { $c += '..' }; Set-Content $p $c"
)

REM ---------- 段 7：安装 pip ----------
REM 嵌入式包不含 pip，从 bootstrap.pypa.io 获取 get-pip.py（CDN 分发，无稳定国内镜像）。
echo 安装 pip...
curl.exe -L --fail --connect-timeout 15 -o get-pip.py "https://bootstrap.pypa.io/get-pip.py"
if exist get-pip.py for %%A in (get-pip.py) do if %%~zA LSS 500000 del get-pip.py
if not exist get-pip.py (
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py' -TimeoutSec 120 } catch { exit 1 }"
)
if exist get-pip.py for %%A in (get-pip.py) do if %%~zA LSS 500000 del get-pip.py
if not exist get-pip.py (
    REM 退化为 ensurepip（部分嵌入式包可用）；3.12.8 的 embed 包不含它，此路大概率不通。
    "%PY%" -m ensurepip --upgrade
    if errorlevel 1 (
        echo [错误] 无法获取 pip。
        echo 请手工下载 https://bootstrap.pypa.io/get-pip.py 放到本目录后重试。
        pause
        exit /b 1
    )
) else (
    "%PY%" get-pip.py --no-warn-script-location
    if errorlevel 1 (
        echo [错误] pip 安装失败，请查看上方输出后重试。
        pause
        exit /b 1
    )
)
del get-pip.py 2>nul

REM ---------- 段 8：安装依赖（官方失败切清华镜像） ----------
REM 先试官方 PyPI，失败切清华镜像。不让用户选——用户不知道自己该用哪个。
echo 安装 Python 依赖（首次需要下载，请耐心等待）...
"%PY%" -m pip install -r requirements.txt --no-warn-script-location
if errorlevel 1 (
    echo [提示] 官方源安装失败，切换清华镜像重试...
    "%PY%" -m pip install -r requirements.txt --no-warn-script-location -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
)
if errorlevel 1 (
    echo [错误] 依赖安装失败，请把上方输出复制提交 issue：
    echo   https://github.com/Eternal-Wanderer-Vegetable/Stella_project/issues
    pause
    exit /b 1
)

REM ---------- 段 9：清理并进入启动 ----------
del "%PY_ZIP%" 2>nul

:run
if not exist ".env" (
    echo 未检测到配置文件，进入配置向导...
    "%PY%" -m deploy init
    if errorlevel 1 (
        echo 配置未完成，退出。
        pause
        exit /b 1
    )
)
"%PY%" -m deploy start
pause

goto :eof

:try_download
REM 参数 1=URL 2=输出文件。curl 失败或产物异常（小于 1MB）都返回 errorlevel 1。
curl.exe -L --fail --connect-timeout 15 --retry 2 -o "%~2" "%~1"
if not exist "%~2" exit /b 1
if exist "%~2" for %%A in ("%~2") do if %%~zA LSS 1048576 exit /b 1
exit /b 0

:try_download_ps
REM 参数同上。curl 不可用的旧系统走 PowerShell；产物小于 1MB 视为失败。
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%~1' -OutFile '%~2' -TimeoutSec 120 } catch { exit 1 }"
if not exist "%~2" exit /b 1
if exist "%~2" for %%A in ("%~2") do if %%~zA LSS 1048576 exit /b 1
exit /b 0
