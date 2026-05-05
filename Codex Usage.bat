@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "LAUNCHER=%SCRIPT_DIR%scripts\start_context_limit_widget.ps1"

if not exist "%LAUNCHER%" (
    echo Codex Usage launcher not found:
    echo %LAUNCHER%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%LAUNCHER%" --position saved %*
if errorlevel 1 (
    echo Failed to start Codex Usage.
    pause
    exit /b 1
)
