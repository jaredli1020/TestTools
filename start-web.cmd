@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\casecraft.exe" (
  echo [CaseCraft] .venv is missing. Run: py -m venv .venv
  echo [CaseCraft] Then run: .venv\Scripts\pip install -e ".[web]"
  pause
  exit /b 1
)

echo [CaseCraft] Starting local workspace at http://127.0.0.1:8001
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8001"
".venv\Scripts\casecraft.exe" web --host 127.0.0.1 --port 8001

echo.
echo [CaseCraft] Service stopped.
pause
