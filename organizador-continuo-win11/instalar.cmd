@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" %*
if errorlevel 1 (
  echo.
  echo Falha na instalacao. Execute como administrador e confira a mensagem acima.
  pause
  exit /b 1
)
pause
