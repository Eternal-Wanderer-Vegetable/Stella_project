@echo off
REM 本文件为 GBK(CP936) 编码，原因见 start.bat 头部注释。
chcp 936 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
    echo 尚未安装运行环境，请先运行 start.bat。
    pause
    exit /b 1
)
runtime\python.exe -m deploy stop
pause
