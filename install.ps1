# Points Claude Code at DeepSeek, installing Claude Code first if it is missing.
# Runs on Windows PowerShell 5.1 and PowerShell 7+.
# Settings follow https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/

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

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Have { param([string]$Name) [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

Write-Host "`nClaude Code on DeepSeek" -ForegroundColor Cyan
Write-Host "=======================`n" -ForegroundColor Cyan

# --- key ---
$key = "$env:DEEPSEEK_API_KEY".Trim()
if (-not $key) {
    $secure = Read-Host 'Paste your DeepSeek API key, then press Enter (it stays hidden)' -AsSecureString
    $key = (New-Object System.Net.NetworkCredential('', $secure)).Password.Trim()
}
if (-not $key) { Fail 'The installer needs a DeepSeek API key.' 'Create one at https://platform.deepseek.com then run this again.' }

# --- verify the key before changing or installing anything ---
Write-Host 'Checking the key...' -ForegroundColor Gray
# 256 tokens for this one check: these models think first, and a small budget leaves no reply.
$body = @{ model = $Small; max_tokens = 256; messages = @(@{ role = 'user'; content = 'Say PONG' }) } | ConvertTo-Json -Depth 5
try {
    $reply = Invoke-RestMethod "$Base/v1/messages" -Method Post -TimeoutSec 60 -ContentType 'application/json' -Body $body `
        -Headers @{ Authorization = "Bearer $key"; 'anthropic-version' = '2023-06-01' }
    $said = ($reply.content | Where-Object { $_.type -eq 'text' } | Select-Object -First 1).text
    if ($said) { Write-Host "  Key works. DeepSeek replied: $said" -ForegroundColor Green }
    else { Write-Host '  Key works.' -ForegroundColor Green }
} catch {
    $raw = if ($_.ErrorDetails) { $_.ErrorDetails.Message } else { $_.Exception.Message }
    try { $detail = ($raw | ConvertFrom-Json).error.message } catch { $detail = $raw }
    Fail "DeepSeek said: $detail" 'Check the key and your balance at https://platform.deepseek.com, then run this again.'
}

# --- Claude Code and its prerequisites ---
if (Have 'claude') {
    Write-Host "  Claude Code is already installed." -ForegroundColor Green
} else {
    $winget = Have 'winget'
    foreach ($need in @(
            @{ Cmd = 'node'; Id = 'OpenJS.NodeJS.LTS'; Name = 'Node.js' },
            @{ Cmd = 'git'; Id = 'Git.Git'; Name = 'Git for Windows' })) {
        if (Have $need.Cmd) { continue }
        if (-not $winget) { Fail "$($need.Name) is required and winget is unavailable." "Install $($need.Name) manually, then run this again." }
        Write-Host "  Installing $($need.Name). This takes a few minutes." -ForegroundColor Yellow
        winget install --id $need.Id -e --accept-source-agreements --accept-package-agreements | Out-Host
        Refresh-Path
        if (-not (Have $need.Cmd)) { Fail "$($need.Name) did not install." "Install it manually, reopen PowerShell, then run this again." }
    }

    Write-Host '  Installing Claude Code...' -ForegroundColor Yellow
    & npm install -g @anthropic-ai/claude-code | Out-Host
    Refresh-Path
    if (-not (Have 'claude')) {
        Fail 'Claude Code did not install.' 'Run "npm install -g @anthropic-ai/claude-code" yourself, then run this again.'
    }
    Write-Host "  Claude Code installed: $(& claude --version)" -ForegroundColor Green
}

# --- settings ---
$settings = [ordered]@{
    ANTHROPIC_BASE_URL              = $Base
    ANTHROPIC_AUTH_TOKEN            = $key
    ANTHROPIC_MODEL                 = $Big
    ANTHROPIC_DEFAULT_OPUS_MODEL    = $Big
    ANTHROPIC_DEFAULT_SONNET_MODEL  = $Big
    ANTHROPIC_DEFAULT_HAIKU_MODEL   = $Small
    CLAUDE_CODE_SUBAGENT_MODEL      = $Small
    CLAUDE_CODE_EFFORT_LEVEL        = 'max'
    CLAUDE_CODE_AUTO_COMPACT_WINDOW = '786432'
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
Write-Host "`nNEXT: close this window, open a new PowerShell window, then run:" -ForegroundColor Yellow
Write-Host '  claude' -ForegroundColor Cyan
