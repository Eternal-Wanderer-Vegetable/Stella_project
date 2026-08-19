@echo off
cd /d "%~dp0"


REM Dev-only preview server. ASCII-only on purpose: bat encoding vs code page
REM mismatch garbles output and breaks the parser (UTF-8 file + chcp 936 makes
REM the parser lose bytes and execute fragments of comment lines).
set "PY="
if exist "..\runtime\python.exe" set "PY=..\runtime\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)


if not defined PY (
    echo [ERROR] No usable Python found.
    echo   1. Run this script from an activated conda/venv shell
    echo   2. Or run start.bat once in the project root to fetch runtime\
    echo   3. Or add Python to PATH
    pause
    exit /b 1
)


echo Using Python: %PY%
echo Preview: http://localhost:8765
echo Close this window to stop.
echo.


REM Serve src\ as document root so ./mock\... and ./api.js resolve.
REM ES module + fetch need a real origin; file:// is blocked by CORS, which makes
REM the module script never run (only static HTML shows, #root stays empty).
REM Tauri serves the frontend over a custom protocol, so this is preview-only.
start "" http://localhost:8765
"%PY%" -m http.server 8765 --directory src


echo.
echo Server stopped.
pause