# Starts the Hetzner Claude Code bridge in this window.
# Runs on Windows PowerShell 5.1 and PowerShell 7+.

$ErrorActionPreference = 'Stop'
$InstallDir = Join-Path $env:LOCALAPPDATA 'HetznerClaudeCode'
$ServerPy = Join-Path $InstallDir 'proxy\server.py'

function Stop-Friendly {
    param([string]$Text)
    Write-Host $Text -ForegroundColor Red
    exit 1
}

if (Test-Path $ServerPy) { } else {
    Stop-Friendly 'The bridge is missing. Run install.ps1 first.'
}

$config = $null
$configPath = Join-Path $InstallDir 'config.json'
if (Test-Path $configPath) {
    try { $config = Get-Content -Raw $configPath | ConvertFrom-Json } catch { $config = $null }
}

$python = $null
if ($config -and $config.pythonExe -and (Test-Path $config.pythonExe)) {
    $python = $config.pythonExe
} else {
    foreach ($name in @('py', 'python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -like '*\WindowsApps\*') { continue }
        if ($cmd) { $python = $cmd.Source; break }
    }
}
if ($null -eq $python) {
    Stop-Friendly 'Python is missing. Run install.ps1 again.'
}

# Settings saved by the installer live in the user environment.
foreach ($name in @('HETZNER_API_KEY', 'HCC_LOCAL_TOKEN', 'HETZNER_MODEL')) {
    $current = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrEmpty($current)) {
        $saved = [Environment]::GetEnvironmentVariable($name, 'User')
        if ($saved) { Set-Item -Path ('Env:' + $name) -Value $saved }
    }
}

if ([string]::IsNullOrEmpty($env:HETZNER_API_KEY)) {
    Stop-Friendly 'HETZNER_API_KEY is missing. Run install.ps1 first.'
}
if ([string]::IsNullOrEmpty($env:HCC_LOCAL_TOKEN)) {
    Stop-Friendly 'HCC_LOCAL_TOKEN is missing. Run install.ps1 first.'
}
if ([string]::IsNullOrEmpty($env:HETZNER_MODEL)) {
    $env:HETZNER_MODEL = 'Qwen/Qwen3.6-35B-A3B-FP8'
}
if ($config -and $config.port) { $env:HCC_PORT = [string]$config.port }

Write-Host 'Hetzner Claude Code bridge is starting. Keep this window open.' -ForegroundColor Cyan
Set-Location $InstallDir
& $python $ServerPy
