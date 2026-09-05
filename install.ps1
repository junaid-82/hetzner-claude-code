# Points Claude Code at DeepSeek.
# Runs on Windows PowerShell 5.1 and PowerShell 7+.

$ErrorActionPreference = 'Stop'
$Base = 'https://api.deepseek.com/anthropic'
$Big = 'deepseek-v4-pro'
$Small = 'deepseek-v4-flash'

try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

function Fail {
    param([string]$Problem, [string]$Fix)
    Write-Host "`nSetup stopped here." -ForegroundColor Red
    Write-Host "  What happened: $Problem" -ForegroundColor Red
    if ($Fix) { Write-Host "  What to do:    $Fix" -ForegroundColor Yellow }
    exit 1
}

Write-Host "`nClaude Code on DeepSeek" -ForegroundColor Cyan
Write-Host "=======================`n" -ForegroundColor Cyan

# --- key ---
$key = "$env:DEEPSEEK_API_KEY".Trim()
if (-not $key) {
    $secure = Read-Host 'Paste your DeepSeek API key, then press Enter (it stays hidden)' -AsSecureString
    $key = (New-Object System.Net.NetworkCredential('', $secure)).Password.Trim()
}
if (-not $key) { Fail 'The installer needs a DeepSeek API key.' 'Create one at https://platform.deepseek.com then run this again.' }

# --- verify before changing anything ---
Write-Host 'Checking the key...' -ForegroundColor Gray
$body = @{ model = $Small; max_tokens = 32; messages = @(@{ role = 'user'; content = 'Say PONG' }) } | ConvertTo-Json -Depth 5
try {
    $reply = Invoke-RestMethod "$Base/v1/messages" -Method Post -TimeoutSec 60 -ContentType 'application/json' -Body $body `
        -Headers @{ Authorization = "Bearer $key"; 'anthropic-version' = '2023-06-01' }
    Write-Host "  Key works. DeepSeek replied: $($reply.content[0].text)" -ForegroundColor Green
} catch {
    $raw = if ($_.ErrorDetails) { $_.ErrorDetails.Message } else { $_.Exception.Message }
    try { $detail = ($raw | ConvertFrom-Json).error.message } catch { $detail = $raw }
    Fail "DeepSeek said: $detail" 'Check the key and your balance at https://platform.deepseek.com, then run this again.'
}

# --- settings ---
$settings = [ordered]@{
    ANTHROPIC_BASE_URL             = $Base
    ANTHROPIC_AUTH_TOKEN           = $key
    ANTHROPIC_MODEL                = $Big
    ANTHROPIC_DEFAULT_OPUS_MODEL   = $Big
    ANTHROPIC_DEFAULT_SONNET_MODEL = $Big
    ANTHROPIC_DEFAULT_HAIKU_MODEL  = $Small
}

# Keep what was there, so uninstall restores it.
$backup = Join-Path $env:LOCALAPPDATA 'claude-code-deepseek.json'
if (-not (Test-Path $backup)) {
    $previous = [ordered]@{}
    foreach ($n in $settings.Keys) { $previous[$n] = [Environment]::GetEnvironmentVariable($n, 'User') }
    $previous | ConvertTo-Json | Set-Content $backup -Encoding UTF8
}

$replacing = @($settings.Keys | Where-Object {
        $v = [Environment]::GetEnvironmentVariable($_, 'User'); $v -and $v -ne $settings[$_] })
if ($replacing) { Write-Host "  Replacing your current $($replacing -join ', '). Uninstall restores them." -ForegroundColor Yellow }

foreach ($n in $settings.Keys) {
    [Environment]::SetEnvironmentVariable($n, $settings[$n], 'User')
    Set-Item "Env:$n" -Value $settings[$n]
}

# ANTHROPIC_API_KEY outranks ANTHROPIC_AUTH_TOKEN and would send Claude Code elsewhere.
if ([Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY', 'User')) {
    Write-Host "`n  Note: ANTHROPIC_API_KEY is set and takes precedence. Clear it with:" -ForegroundColor Yellow
    Write-Host "  [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY',`$null,'User')" -ForegroundColor Cyan
}

Write-Host "`nDone." -ForegroundColor Green
Write-Host "  Model: $Big  (background tasks use $Small)"
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "`nClaude Code is not installed yet:" -ForegroundColor Yellow
    Write-Host '  npm install -g @anthropic-ai/claude-code' -ForegroundColor Cyan
}
Write-Host "`nNEXT: close this window, open a new PowerShell window, then run:" -ForegroundColor Yellow
Write-Host '  claude' -ForegroundColor Cyan
