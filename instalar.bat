@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Instalando la suite de pruebas de SICEDU...
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
%PY% --version || (echo No se encontro Python. Instala Python 3.11 o superior desde python.org marcando "Add python.exe to PATH". & pause & exit /b 1)
if not exist .venv %PY% -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt || (echo Fallo la instalacion de Playwright. & pause & exit /b 1)
.venv\Scripts\python.exe -m playwright install chromium || (echo Fallo la descarga de Chromium. & pause & exit /b 1)
if not exist .env copy .env.example .env >nul
echo.
echo Listo. Abre el archivo .env con el Bloc de notas, completalo y luego ejecuta preparar.bat
pause
