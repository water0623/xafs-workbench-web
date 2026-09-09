@echo off
setlocal
cd /d "%~dp0"
if exist "desktop\run_xafs_workbench.ps1" cd /d "%~dp0desktop"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Run setup_windows.ps1 first.
  pause
  exit /b 1
)
start "XAFS Workbench" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_xafs_workbench.ps1"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"
endlocal
