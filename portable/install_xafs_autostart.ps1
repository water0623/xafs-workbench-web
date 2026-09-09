$ErrorActionPreference = 'Stop'

$taskName = 'XAFS Workbench Local Service'
$launcher = Join-Path $PSScriptRoot 'run_xafs_workbench.ps1'
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Launcher not found: $launcher"
}

$powershell = Join-Path $PSHOME 'powershell.exe'
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Keeps the local XAFS Workbench backend available at http://127.0.0.1:8765 independently of Codex.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Installed and started: $taskName"
Write-Host 'Open http://127.0.0.1:8765/?v=29'
