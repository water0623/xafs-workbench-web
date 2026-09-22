param(
    [int]$Port = 8765,
    [string]$AccessToken = $env:XAFS_ACCESS_TOKEN
)

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
if (-not $selectedPython) {
    $selectedPython = (Get-Command py -ErrorAction Stop).Source
}

if (-not $AccessToken) {
    $bytes = New-Object byte[] 24
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    $AccessToken = -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

$computerName = [System.Net.Dns]::GetHostName()
$networkUrl = "http://${computerName}:$Port/"
$env:XAFS_HOST = '0.0.0.0'
$env:XAFS_PORT = [string]$Port
$env:XAFS_ACCESS_TOKEN = $AccessToken

Write-Host 'XAFS Workbench 网络服务已准备启动' -ForegroundColor Green
Write-Host "其他电脑访问：$networkUrl"
Write-Host "访问密钥：$AccessToken"
Write-Host '请保持此窗口运行。若无法访问，请允许 Windows 防火墙中的 TCP 端口，或请管理员配置 HTTPS 反向代理。'
Write-Host '按 Ctrl+C 停止服务。'

if ([IO.Path]::GetFileName($selectedPython) -ieq 'py.exe') {
    & $selectedPython -3.11 -m xafs_workbench.webapp
} else {
    & $selectedPython -m xafs_workbench.webapp
}
