@echo off
chcp 65001 >nul
echo.
echo ======================================
echo   AI 助手 UI 设计方案预览
echo ======================================
echo.
echo 正在启动开发服务器...
echo.
echo 启动后，请在浏览器中访问：
echo   http://localhost:5173/assistant-demo
echo.
echo 提示：如果依赖未安装，请先运行 npm install
echo.
echo ======================================
echo.

cd /d "%~dp0"
call npm run dev

pause
