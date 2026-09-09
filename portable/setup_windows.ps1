param([switch]$SkipAutoStart)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $root 'xafs_workbench'))) {
    $root = Join-Path $PSScriptRoot 'desktop'
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'xafs_workbench'))) {
    throw 'The xafs_workbench package is missing. Extract the complete ZIP first.'
}

Write-Host 'Checking Python 3.11 or newer...'
& py -3.11 -c "import sys; assert sys.version_info >= (3, 11)"
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.11 is required. Install it from https://www.python.org/downloads/windows/'
}

$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & py -3.11 -m venv $venv
}
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $root 'requirements-xafs-workbench.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

$config = Join-Path $root 'xafs_workbench.local.ps1'
if (-not (Test-Path -LiteralPath $config)) {
    $line = '$XafsPythonExe = ''' + $python.Replace("'", "''") + ''''
    $line | Set-Content -LiteralPath $config -Encoding UTF8
}

if (-not $SkipAutoStart) {
    & (Join-Path $root 'install_xafs_autostart.ps1')
}

Write-Host 'Workbench installed. Demeter/IFEFFIT and HAMA are still required for native calculations.' -ForegroundColor Green
Start-Process (Join-Path $PSScriptRoot 'launch_workbench.cmd')
