@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if "%~1"=="" (
  .venv\Scripts\python.exe correr.py --listar
  echo.
  echo Ejemplos: correr.bat --modulo Asistencias    correr.bat --rechazados    correr.bat --todo
  pause
  exit /b
)
.venv\Scripts\python.exe correr.py %*
pause
