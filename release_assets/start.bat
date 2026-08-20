@echo off
setlocal enabledelayedexpansion
if defined STELLA_ROOT (
    cd /d "%STELLA_ROOT%"
) else (
    cd /d "%~dp0"
)

rem Stella runtime bootstrap and launcher.
rem --prepare installs Python and dependencies without starting the bot.

set "PY_VER=3.12.10"
set "PY_ZIP=python-%PY_VER%-embed-amd64.zip"
set "PY_SHA256=4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3"
set "RUNTIME_DIR=runtime"
set "PY=%RUNTIME_DIR%\python.exe"

if not exist "%PY%" goto :download
if exist "%RUNTIME_DIR%\.stella-deps-ready" goto :run
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

:run
if /i "%~1"=="--prepare" (
    > "%RUNTIME_DIR%\.stella-deps-ready" echo ready
    exit /b 0
)
if not exist ".env" (
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
