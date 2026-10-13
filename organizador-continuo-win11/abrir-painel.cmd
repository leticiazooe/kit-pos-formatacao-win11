@echo off
setlocal
set "APP=%ProgramFiles%\OrganizadorPC"
if not exist "%APP%\.venv\Scripts\python.exe" (
  echo Organizador PC nao instalado. Execute instalar.cmd como administrador.
  pause
  exit /b 1
)
pushd "%APP%"
"%APP%\.venv\Scripts\python.exe" -m organizador_pc dashboard
set "RESULT=%ERRORLEVEL%"
popd
if not "%RESULT%"=="0" pause
exit /b %RESULT%
