@echo off
REM 本文件为 GBK(CP936) 编码，原因见 start.bat 头部注释。
chcp 936 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
    echo 尚未安装运行环境，请先运行 start.bat。
    pause
    exit /b 1
)
runtime\python.exe -m deploy doctor
echo.
echo 把上面的输出复制下来，可以提交 issue：
echo   https://github.com/Eternal-Wanderer-Vegetable/Stella_project/issues
pause
