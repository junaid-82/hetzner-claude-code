# Puts Claude Code back the way it was.
# Runs on Windows PowerShell 5.1 and PowerShell 7+.

$ErrorActionPreference = 'SilentlyContinue'

$names = @('ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL',
    'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL')

$backup = Join-Path $env:LOCALAPPDATA 'claude-code-deepseek.json'
$previous = if (Test-Path $backup) { Get-Content -Raw $backup | ConvertFrom-Json }

$restored = 0
foreach ($n in $names) {
    $old = if ($previous) { $previous.$n }
    [Environment]::SetEnvironmentVariable($n, $old, 'User')
    if ($old) { $restored++ }
}
Remove-Item $backup -Force

Write-Host 'Claude Code is no longer pointed at DeepSeek.' -ForegroundColor Green
if ($restored) { Write-Host "Restored $restored earlier setting(s)." -ForegroundColor Gray }
Write-Host 'Open a new PowerShell window for the change to take effect.'
