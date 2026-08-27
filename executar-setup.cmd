@echo off
title Setup Windows 11

cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando permissao de Administrador...
    powershell.exe -NoProfile -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows11.ps1"

if errorlevel 1 (
    echo.
    echo O script terminou com erro.
    pause
)
