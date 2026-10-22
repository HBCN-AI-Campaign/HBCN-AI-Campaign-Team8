@echo off
rem 轻量 OCR 文档识别 —— 一键运行（Windows）
rem 用法：
rem   run.bat               识别 samples 目录下所有文件
rem   run.bat 文件/目录 ...  识别指定文件或目录
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境，请先按 README.md 完成环境准备。
    exit /b 1
)

set PADDLE_PDX_MODEL_SOURCE=BOS
set PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

if "%~1"=="" (
    ".venv\Scripts\python.exe" -m ocr_service.cli samples
) else (
    ".venv\Scripts\python.exe" -m ocr_service.cli %*
)
