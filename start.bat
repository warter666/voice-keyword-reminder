@echo off
rem 双击运行:读取同目录 config.toml 开始监听
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [!] 未找到 .venv 虚拟环境,请先按 README.md 安装依赖
    pause
    exit /b 1
)
".venv\Scripts\python.exe" reminder.py
pause
