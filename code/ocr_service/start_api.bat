@echo off
rem OCR 识别 API 启动脚本（Windows）
rem 双击即可启动，无需手动激活虚拟环境。
chcp 65001 >nul
cd /d "%~dp0"

set VENV_PY=.venv\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo [错误] 未找到虚拟环境，请先按 README.md 完成环境准备。
    exit /b 1
)

set PADDLE_PDX_MODEL_SOURCE=BOS
set PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

echo 正在启动 OCR 识别 API ...
echo 服务地址：http://127.0.0.1:7888
echo 接口文档：http://127.0.0.1:7888/docs
echo 按 Ctrl+C 停止服务。
echo.

"%VENV_PY%" -m uvicorn main:app --host 127.0.0.1 --port 7888
