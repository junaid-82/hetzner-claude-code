$ErrorActionPreference = 'SilentlyContinue'
$InstallDir = Join-Path $env:LOCALAPPDATA 'HetznerClaudeCode'

$stop = Join-Path $InstallDir 'stop.ps1'
if (Test-Path $stop) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stop }

$vars = @(
  'HETZNER_API_KEY', 'HETZNER_MODEL', 'HCC_LOCAL_TOKEN',
  'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL',
  'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
  'ANTHROPIC_DEFAULT_HAIKU_MODEL'
)
foreach ($name in $vars) {
    [Environment]::SetEnvironmentVariable($name, $null, 'User')
}

if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }

Write-Host 'Hetzner Claude Code bridge removed.' -ForegroundColor Green
Write-Host 'Open a new PowerShell window for environment changes to take effect.'