# Installs the Hetzner Claude Code bridge.
# Runs on Windows PowerShell 5.1 and PowerShell 7+, using APIs available in both.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'https://raw.githubusercontent.com/junaid-82/hetzner-claude-code/main'
$InstallDir = Join-Path $env:LOCALAPPDATA 'HetznerClaudeCode'
$Port = 8787
$Model = 'Qwen/Qwen3.6-35B-A3B-FP8'

# GitHub requires TLS 1.2.
try {
    $protocol = [Net.ServicePointManager]::SecurityProtocol
    [Net.ServicePointManager]::SecurityProtocol = $protocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

function Write-Step { param([string]$Text) Write-Host $Text -ForegroundColor Gray }
function Write-Good { param([string]$Text) Write-Host $Text -ForegroundColor Green }
function Write-Note { param([string]$Text) Write-Host $Text -ForegroundColor Yellow }

function Stop-Friendly {
    param([string]$Problem, [string]$Fix)
    Write-Host ''
    Write-Host 'Setup stopped here.' -ForegroundColor Red
    Write-Host ('  What happened: ' + $Problem) -ForegroundColor Red
    if ($Fix) { Write-Host ('  What to do:    ' + $Fix) -ForegroundColor Yellow }
    Write-Host ''
    exit 1
}

Write-Host ''
Write-Host 'Hetzner Claude Code' -ForegroundColor Cyan
Write-Host '===================' -ForegroundColor Cyan
Write-Host ('PowerShell ' + $PSVersionTable.PSVersion.ToString()) -ForegroundColor DarkGray
Write-Host ''

# ------------------------------------------------------------------ local token

function New-LocalToken {
    # Create()/GetBytes(byte[]) is available on every supported runtime.
    $bytes = New-Object 'System.Byte[]' 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $token = [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_').Replace('=', '')
    [Array]::Clear($bytes, 0, $bytes.Length)
    return $token
}

# ------------------------------------------------------------------ python

function Test-PythonCandidate {
    param([string]$Exe, [string[]]$PreArgs)
    try {
        # The probe stays free of quotes so every PowerShell host passes it to Python intact.
        $probe = 'import sys; print(sys.version_info[0]); print(sys.version_info[1]); print(sys.executable)'
        $argList = @()
        if ($PreArgs) { $argList += $PreArgs }
        $argList += @('-c', $probe)

        $out = & $Exe @argList 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $lines = @($out | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ } )
            if ($lines.Count -ge 3) {
                $version = [version]($lines[-3] + '.' + $lines[-2])
                if ($version -ge [version]'3.8') {
                    return [pscustomobject]@{ Version = $version; Executable = $lines[-1] }
                }
            }
        }
    } catch { }
    return $null
}

function Find-Python {
    # Real interpreters live outside WindowsApps, where the Store keeps a placeholder alias.
    foreach ($candidate in @(
            @{ Name = 'py';      Pre = @('-3') },
            @{ Name = 'python';  Pre = @() },
            @{ Name = 'python3'; Pre = @() })) {
        $cmd = Get-Command $candidate.Name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -like '*\WindowsApps\*') { continue }
        if ($cmd) {
            $found = Test-PythonCandidate -Exe $candidate.Name -PreArgs $candidate.Pre
            if ($found) { return $found }
        }
    }
    return $null
}

Write-Step 'Looking for Python...'
$python = Find-Python
if ($null -eq $python) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Note 'Installing Python 3.12. This takes a few minutes.'
        try {
            winget install --id Python.Python.3.12 -e --scope user --accept-source-agreements --accept-package-agreements | Out-Host
        } catch {
            Stop-Friendly 'The automatic Python install failed.' 'Install Python from https://www.python.org/downloads/, tick "Add python.exe to PATH", then run the installer again.'
        }
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $python = Find-Python
    }
}
if ($null -eq $python) {
    Stop-Friendly 'Python 3.8 or newer is required.' 'Install Python from https://www.python.org/downloads/, tick "Add python.exe to PATH", close this window, open PowerShell again, then run the installer again.'
}
Write-Good ('  Python ' + $python.Version + ' at ' + $python.Executable)

# ------------------------------------------------------------------ api key

$key = $env:HETZNER_API_KEY
if ([string]::IsNullOrWhiteSpace($key)) {
    $secure = Read-Host 'Paste your Hetzner Inference API key, then press Enter (it stays hidden)' -AsSecureString
    $key = (New-Object System.Net.NetworkCredential('', $secure)).Password
}
if ($key) { $key = $key.Trim() }
if ([string]::IsNullOrWhiteSpace($key)) {
    Stop-Friendly 'The installer needs a Hetzner API key.' 'Run the installer again and paste the key at the prompt. It stays hidden while you paste, so paste and press Enter.'
}

# ------------------------------------------------------------------ port

try {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        if ($owner -and $owner.ProcessName -notmatch 'python') {
            Stop-Friendly ("Port $Port is already used by " + $owner.ProcessName + '.') 'Close that program, then run the installer again.'
        }
    }
} catch { }

# ------------------------------------------------------------------ files

New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'proxy') | Out-Null

function Get-Payload {
    param([string]$RelativePath, [string]$Destination)
    # Files beside this script win, so a git clone installs itself.
    if ($PSScriptRoot) {
        $local = Join-Path $PSScriptRoot $RelativePath
        if (Test-Path $local) {
            Copy-Item $local $Destination -Force
            return
        }
    }
    Invoke-WebRequest -Uri ($Repo + '/' + ($RelativePath -replace '\\', '/')) -OutFile $Destination -UseBasicParsing
}

Write-Step 'Installing the bridge...'
try {
    Get-Payload 'proxy/server.py' (Join-Path $InstallDir 'proxy\server.py')
    Get-Payload 'start.ps1' (Join-Path $InstallDir 'start.ps1')
    Get-Payload 'stop.ps1'  (Join-Path $InstallDir 'stop.ps1')
} catch {
    Stop-Friendly ('The download failed: ' + $_.Exception.Message) 'Check your internet connection, then run the installer again.'
}

# ------------------------------------------------------------------ settings

$localToken = New-LocalToken

$settings = [ordered]@{
    'HETZNER_API_KEY'                   = $key
    'HETZNER_MODEL'                     = $Model
    'HCC_LOCAL_TOKEN'                   = $localToken
    'ANTHROPIC_BASE_URL'                = ('http://127.0.0.1:' + $Port)
    'ANTHROPIC_AUTH_TOKEN'              = $localToken
    'ANTHROPIC_MODEL'                   = $Model
    'ANTHROPIC_DEFAULT_SONNET_MODEL'    = $Model
    'ANTHROPIC_DEFAULT_OPUS_MODEL'      = $Model
    'ANTHROPIC_DEFAULT_HAIKU_MODEL'     = $Model
    # Hetzner grants 10 requests per minute; reserving that budget for direct work
    # keeps Claude Code responsive.
    'DISABLE_NON_ESSENTIAL_MODEL_CALLS' = '1'
}

# Record the current values so uninstall restores them.
$configPath = Join-Path $InstallDir 'config.json'
$previous = $null
if (Test-Path $configPath) {
    try { $previous = (Get-Content -Raw $configPath | ConvertFrom-Json).previousEnv } catch { $previous = $null }
}
if ($null -eq $previous) {
    $previous = [ordered]@{}
    foreach ($name in $settings.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'User')
    }
}

$replacing = @()
foreach ($name in @('ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL')) {
    $existing = [Environment]::GetEnvironmentVariable($name, 'User')
    if ($existing -and $existing -ne $settings[$name]) { $replacing += $name }
}
if ($replacing.Count -gt 0) {
    Write-Note ('This points Claude Code at Hetzner and replaces your current ' + ($replacing -join ', ') + '.')
    Write-Note 'Uninstalling restores the previous values.'
}

foreach ($name in $settings.Keys) {
    [Environment]::SetEnvironmentVariable($name, $settings[$name], 'User')
    Set-Item -Path ('Env:' + $name) -Value $settings[$name]
}

$pythonw = Join-Path (Split-Path -Parent $python.Executable) 'pythonw.exe'
if (Test-Path $pythonw) { $launcher = $pythonw } else { $launcher = $python.Executable }

[ordered]@{
    model       = $Model
    port        = $Port
    pythonExe   = $python.Executable
    pythonwExe  = $launcher
    installedAt = (Get-Date).ToString('s')
    previousEnv = $previous
} | ConvertTo-Json -Depth 5 | Set-Content -Path $configPath -Encoding UTF8

# ------------------------------------------------------------------ start

Write-Step 'Starting the bridge and checking your Hetzner key...'
& (Join-Path $InstallDir 'stop.ps1') | Out-Null

$logPath = Join-Path $InstallDir 'bridge.log'
Start-Process -FilePath $launcher `
    -ArgumentList @((Join-Path $InstallDir 'proxy\server.py')) `
    -WorkingDirectory $InstallDir `
    -WindowStyle Hidden `
    -RedirectStandardError $logPath | Out-Null

$headers = @{ Authorization = ('Bearer ' + $localToken) }
$ready = $false
$reason = ''
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $Port + '/health') -Headers $headers -TimeoutSec 3
        if ($health.ok) { $ready = $true; break }
    } catch { $reason = $_.Exception.Message }
}
if ($ready -eq $false) {
    $logTail = ''
    if (Test-Path $logPath) { $logTail = (Get-Content $logPath -Tail 5) -join ' / ' }
    Stop-Friendly ('The bridge failed to answer. ' + $reason + ' ' + $logTail) 'Run this to see the full error: powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\HetznerClaudeCode\start.ps1"'
}

# ------------------------------------------------------------------ verify

$verify = $null
try {
    $verify = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $Port + '/verify') -Headers $headers -TimeoutSec 40
} catch { }

if ($null -eq $verify) {
    Write-Note 'The bridge is running. The Hetzner check timed out, so try "claude" and see how it goes.'
} elseif ($verify.ok -eq $false) {
    Stop-Friendly ('Hetzner replied: ' + $verify.error) 'Check the key at https://console.hetzner.com, then run the installer again.'
} elseif ($verify.model_available -eq $false) {
    Write-Note ('Your account currently offers: ' + ($verify.available_models -join ', '))
    Write-Note ('Switch model with: [Environment]::SetEnvironmentVariable("HETZNER_MODEL","<model>","User")')
} else {
    Write-Good ('  Hetzner key works, model available: ' + $Model)
}

# ------------------------------------------------------------------ done

Write-Host ''
Write-Good 'Installed successfully.'
Write-Host ('Model:  ' + $Model)
Write-Host ('Bridge: http://127.0.0.1:' + $Port)
Write-Host ''

if ($null -eq (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Note 'Claude Code is still missing. Install it with:'
    Write-Host '  npm install -g @anthropic-ai/claude-code' -ForegroundColor Cyan
    Write-Host ''
}

Write-Host 'NEXT: close this window, open a new PowerShell window, then run:' -ForegroundColor Yellow
Write-Host '  claude' -ForegroundColor Cyan
Write-Host ''
Write-Host 'After a restart, start the bridge again with:' -ForegroundColor Gray
Write-Host ('  powershell -ExecutionPolicy Bypass -File "' + (Join-Path $InstallDir 'start.ps1') + '"') -ForegroundColor Gray
Write-Host ''
Write-Host 'Your Hetzner key lives in your Windows user account and travels only to Hetzner.' -ForegroundColor DarkGray
