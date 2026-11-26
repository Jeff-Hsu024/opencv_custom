@echo off
cd /d "%~dp0"
python tools/install_platform_tools.py || exit /b 1
where wails >nul 2>&1 || (
    echo Install Wails CLI: go install github.com/wailsapp/wails/v2/cmd/wails@latest
    exit /b 1
)
wails dev
