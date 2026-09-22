@echo off
setlocal
cd /d "%~dp0"
if exist "XAFS-Workbench.exe" (
  "XAFS-Workbench.exe" --network
  exit /b %errorlevel%
)
if exist "desktop\run_xafs_workbench_network.ps1" cd /d "%~dp0desktop"
if not exist "run_xafs_workbench_network.ps1" (
  echo Network launcher is missing. Extract the complete release package first.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_xafs_workbench_network.ps1"
endlocal
