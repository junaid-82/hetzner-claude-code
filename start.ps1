$ErrorActionPreference = 'Stop'
$InstallDir = Join-Path $env:LOCALAPPDATA 'HetznerClaudeCode'
$Python = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } elseif (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { throw 'Python is not installed.' }

if (-not $env:HETZNER_API_KEY) {
    $env:HETZNER_API_KEY = [Environment]::GetEnvironmentVariable('HETZNER_API_KEY', 'User')
}
if (-not $env:HCC_LOCAL_TOKEN) {
    $env:HCC_LOCAL_TOKEN = [Environment]::GetEnvironmentVariable('HCC_LOCAL_TOKEN', 'User')
}
if (-not $env:HETZNER_MODEL) {
    $env:HETZNER_MODEL = [Environment]::GetEnvironmentVariable('HETZNER_MODEL', 'User')
}

if (-not $env:HETZNER_API_KEY) { throw 'HETZNER_API_KEY is not configured. Run install.ps1 first.' }
if (-not $env:HCC_LOCAL_TOKEN) { throw 'HCC_LOCAL_TOKEN is not configured. Run install.ps1 first.' }
if (-not $env:HETZNER_MODEL) { $env:HETZNER_MODEL = 'Qwen/Qwen3.6-35B-A3B-FP8' }

Set-Location $InstallDir
& $Python (Join-Path $InstallDir 'proxy\server.py')
