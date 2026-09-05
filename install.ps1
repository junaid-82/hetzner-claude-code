$ErrorActionPreference = 'Stop'
$Repo = 'https://raw.githubusercontent.com/junaid-82/hetzner-claude-code/main'
$InstallDir = Join-Path $env:LOCALAPPDATA 'HetznerClaudeCode'

Write-Host ''
Write-Host 'Hetzner Claude Code' -ForegroundColor Cyan
Write-Host '===================' -ForegroundColor Cyan
Write-Host ''

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) { return 'py' }
    if (Get-Command python -ErrorAction SilentlyContinue) { return 'python' }
    return $null
}

$Python = Get-PythonCommand
if (-not $Python) {
    $Winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($Winget) {
        Write-Host 'Python was not found. Installing Python 3.12 with winget...' -ForegroundColor Yellow
        winget install --id Python.Python.3.12 -e --scope user --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $Python = Get-PythonCommand
    }
}
if (-not $Python) { throw 'Python 3 is required. Install Python 3.12+ and run this installer again.' }

$secureKey = Read-Host 'Enter your Hetzner Inference API key' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
if ([string]::IsNullOrWhiteSpace($key)) { throw 'No Hetzner API key supplied.' }

New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'proxy') | Out-Null
Write-Host 'Downloading bridge...' -ForegroundColor Gray
Invoke-WebRequest -Uri "$Repo/proxy/server.py" -OutFile (Join-Path $InstallDir 'proxy\server.py')
Invoke-WebRequest -Uri "$Repo/start.ps1" -OutFile (Join-Path $InstallDir 'start.ps1')
Invoke-WebRequest -Uri "$Repo/stop.ps1" -OutFile (Join-Path $InstallDir 'stop.ps1')

$localToken = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$model = 'Qwen/Qwen3.6-35B-A3B-FP8'

[Environment]::SetEnvironmentVariable('HETZNER_API_KEY', $key, 'User')
[Environment]::SetEnvironmentVariable('HETZNER_MODEL', $model, 'User')
[Environment]::SetEnvironmentVariable('HCC_LOCAL_TOKEN', $localToken, 'User')
[Environment]::SetEnvironmentVariable('ANTHROPIC_BASE_URL', 'http://127.0.0.1:8787', 'User')
[Environment]::SetEnvironmentVariable('ANTHROPIC_AUTH_TOKEN', $localToken, 'User')
[Environment]::SetEnvironmentVariable('ANTHROPIC_MODEL', $model, 'User')
[Environment]::SetEnvironmentVariable('ANTHROPIC_DEFAULT_SONNET_MODEL', $model, 'User')
[Environment]::SetEnvironmentVariable('ANTHROPIC_DEFAULT_OPUS_MODEL', $model, 'User')
[Environment]::SetEnvironmentVariable('ANTHROPIC_DEFAULT_HAIKU_MODEL', $model, 'User')

$env:HETZNER_API_KEY = $key
$env:HETZNER_MODEL = $model
$env:HCC_LOCAL_TOKEN = $localToken
$env:ANTHROPIC_BASE_URL = 'http://127.0.0.1:8787'
$env:ANTHROPIC_AUTH_TOKEN = $localToken
$env:ANTHROPIC_MODEL = $model
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = $model
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = $model
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = $model

Write-Host 'Starting local bridge and checking Hetzner...' -ForegroundColor Gray
$startScript = Join-Path $InstallDir 'start.ps1'
Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$startScript`"" -WindowStyle Minimized

$ready = $false
$lastError = ''
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/health' -Headers @{ Authorization = "Bearer $localToken" } -TimeoutSec 3
        if ($health.ok) { $ready = $true; break }
        $lastError = $health.error
    } catch { $lastError = $_.Exception.Message }
}
if (-not $ready) { throw "The bridge did not verify successfully. $lastError Check %LOCALAPPDATA%\HetznerClaudeCode and run start.ps1 manually." }

Write-Host ''
Write-Host 'Installed successfully.' -ForegroundColor Green
Write-Host "Model: $model"
Write-Host 'Proxy: http://127.0.0.1:8787'
Write-Host ''
Write-Host 'IMPORTANT: open a NEW PowerShell window, then run:' -ForegroundColor Yellow
Write-Host '  claude' -ForegroundColor Cyan
Write-Host ''
Write-Host 'The Hetzner key is stored only in your Windows user environment; it is not written to the repository.' -ForegroundColor Gray
