$ErrorActionPreference = 'Stop'
$localConfig = Join-Path $PSScriptRoot 'xafs_workbench.local.ps1'
if (Test-Path -LiteralPath $localConfig) {
    . $localConfig
}
$pythonCandidates = @(
    $env:XAFS_PYTHON_EXE,
    $XafsPythonExe,
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
) | Where-Object { $_ }

$selectedPython = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($selectedPython) {
    & $selectedPython -m xafs_workbench.webapp
} else {
    py -3.11 -m xafs_workbench.webapp
}
