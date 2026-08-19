@echo off
chcp 936 >nul
cd /d "%~dp0"
echo 原型预览：http://localhost:8765
echo 关闭本窗口即停止。
echo.
REM ES module 与 fetch 需要真实 origin，file:// 下会被 CORS 拦住导致脚本不执行。
REM Tauri 通过自定义协议提供前端，因此移植后无此问题——只有本地预览需要起服务。
start "" http://localhost:8765
python -m http.server 8765