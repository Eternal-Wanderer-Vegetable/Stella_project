@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Stella runtime bootstrap and launcher.
rem --prepare installs Python and dependencies without starting the bot.

set "PY_VER=3.12.10"
set "PY_ZIP=python-%PY_VER%-embed-amd64.zip"
set "PY_SHA256=4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3"
set "RUNTIME_DIR=runtime"
set "PY=%RUNTIME_DIR%\python.exe"
set "DEPS_MARKER=%RUNTIME_DIR%\.stella-deps-ready"

rem The deps marker stores the sha256 of requirements.txt, not a fixed string.
rem Upgrades reuse the whole runtime/ directory to avoid a 100MB download; a
rem content-free marker would then mean "deps ready" forever and new
rem dependencies would never be installed. Keep this rule in sync with
rem stella-installer/src-tauri/src/python.rs (deps_marker_matches).
if not exist "%PY%" goto :download
call :req_hash
if not exist "%DEPS_MARKER%" goto :install
set "MARKED="
set /p MARKED=<"%DEPS_MARKER%"
if /i "!MARKED!"=="!REQ_HASH!" goto :run
echo Dependencies changed since the last run. Reinstalling...
goto :install

:download
echo Preparing the embedded Python runtime. This may take a few minutes.
call :try_download "https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%" "%PY_ZIP%"
if errorlevel 1 call :try_download "https://mirrors.huaweicloud.com/python/%PY_VER%/%PY_ZIP%" "%PY_ZIP%"
if errorlevel 1 call :try_download_ps "https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%" "%PY_ZIP%"
if errorlevel 1 call :try_download_ps "https://mirrors.huaweicloud.com/python/%PY_VER%/%PY_ZIP%" "%PY_ZIP%"
if errorlevel 1 (
    echo [ERROR] Failed to download the Python runtime.
    if /i not "%~1"=="--prepare" pause
    exit /b 1
)

for /f "skip=1 tokens=* delims=" %%h in ('certutil -hashfile "%PY_ZIP%" SHA256') do (
    set "HASH=%%h"
    goto :hash_done
)
:hash_done
set "HASH=!HASH: =!"
if /i not "!HASH!"=="%PY_SHA256%" (
    echo [ERROR] Python runtime checksum verification failed.
    del "%PY_ZIP%" 2>nul
    if /i not "%~1"=="--prepare" pause
    exit /b 1
)

echo Extracting the Python runtime...
powershell -NoProfile -Command "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%RUNTIME_DIR%' -Force"
if errorlevel 1 (
    echo [ERROR] Failed to extract the Python runtime.
    del "%PY_ZIP%" 2>nul
    if /i not "%~1"=="--prepare" pause
    exit /b 1
)

:install
rem Enable site-packages and add the project root to sys.path.
for %%f in ("%RUNTIME_DIR%\python*._pth") do (
    powershell -NoProfile -Command "$p='%%~f'; $c=Get-Content $p; $c = $c -replace '^#import site','import site'; if ($c -notcontains '..') { $c += '..' }; Set-Content $p $c"
)

echo Installing pip...
curl.exe -L --fail --connect-timeout 15 -o get-pip.py "https://bootstrap.pypa.io/get-pip.py"
if exist get-pip.py for %%A in (get-pip.py) do if %%~zA LSS 500000 del get-pip.py
if not exist get-pip.py (
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py' -TimeoutSec 120 } catch { exit 1 }"
)
if exist get-pip.py for %%A in (get-pip.py) do if %%~zA LSS 500000 del get-pip.py
if not exist get-pip.py (
    "%PY%" -m ensurepip --upgrade
    if errorlevel 1 (
        echo [ERROR] Failed to install pip.
        if /i not "%~1"=="--prepare" pause
        exit /b 1
    )
) else (
    "%PY%" get-pip.py --no-warn-script-location
    if errorlevel 1 (
        echo [ERROR] Failed to install pip.
        if /i not "%~1"=="--prepare" pause
        exit /b 1
    )
)
del get-pip.py 2>nul

rem 装 setuptools/wheel：嵌入式 Python 只带标准库，而现在的 get-pip.py 只装 pip。
rem 少了它们，任何「只发源码包、不发 wheel」的依赖都会以
rem   BackendUnavailable: Cannot import 'setuptools.build_meta'
rem 失败（v3.0.0 预发布就是被 qrcode_terminal 这么卡住的）。
rem 失败不阻断：绝大多数依赖有 wheel，真缺了下一步会报更具体的错。
echo Installing build tools...
"%PY%" -m pip install setuptools wheel --no-warn-script-location
if errorlevel 1 (
    "%PY%" -m pip install setuptools wheel --no-warn-script-location -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
)

echo Installing Python dependencies. This may take a few minutes.
"%PY%" -m pip install -r requirements.txt --no-warn-script-location
if errorlevel 1 (
    echo The default package index failed. Retrying with the mirror...
    "%PY%" -m pip install -r requirements.txt --no-warn-script-location -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
)
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies.
    if /i not "%~1"=="--prepare" pause
    exit /b 1
)

del "%PY_ZIP%" 2>nul

rem Record which requirements.txt these dependencies were installed from.
call :req_hash
> "%DEPS_MARKER%" echo !REQ_HASH!

:run
if /i "%~1"=="--prepare" (
    exit /b 0
)
rem Where the user's .env lives is decided by config/home.py (STELLA_HOME may point
rem outside this directory), so ask Python instead of assuming ".\.env".
set "ENV_FILE=.env"
for /f "usebackq delims=" %%p in (`"%PY%" -m deploy paths --env-file 2^>nul`) do set "ENV_FILE=%%p"

rem First run in a freshly extracted directory: offer to import from the previous
rem installation instead of making the user copy files by hand. The dry run also
rem verifies the whole import (including the database upgrade) before we ask.
if not exist "!ENV_FILE!" (
    echo Looking for a previous Stella installation...
    "%PY%" -m deploy migrate --dry-run >nul 2>&1
    if not errorlevel 1 (
        echo.
        echo A previous installation with your configuration and memories was found.
        set "IMPORT_CHOICE="
        set /p IMPORT_CHOICE="Import it now? [Y/n] "
        if /i not "!IMPORT_CHOICE!"=="n" (
            "%PY%" -m deploy migrate
        )
    )
)
if not exist "!ENV_FILE!" (
    echo No configuration file found. Starting the configuration wizard...
    "%PY%" -m deploy init
    if errorlevel 1 (
        echo [ERROR] Configuration was not completed.
        pause
        exit /b 1
    )
)
"%PY%" -m deploy start
pause
exit /b %errorlevel%

:req_hash
rem SHA256 of requirements.txt into REQ_HASH ("none" when the file is missing).
set "REQ_HASH=none"
if not exist "requirements.txt" exit /b 0
for /f "skip=1 tokens=* delims=" %%h in ('certutil -hashfile "requirements.txt" SHA256') do (
    set "REQ_HASH=%%h"
    goto :req_hash_done
)
:req_hash_done
set "REQ_HASH=!REQ_HASH: =!"
exit /b 0

:try_download
curl.exe -L --fail --connect-timeout 15 --retry 2 -o "%~2" "%~1"
if not exist "%~2" exit /b 1
if exist "%~2" for %%A in ("%~2") do if %%~zA LSS 1048576 exit /b 1
exit /b 0

:try_download_ps
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%~1' -OutFile '%~2' -TimeoutSec 120 } catch { exit 1 }"
if not exist "%~2" exit /b 1
if exist "%~2" for %%A in ("%~2") do if %%~zA LSS 1048576 exit /b 1
exit /b 0
