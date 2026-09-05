# Removes the Hetzner Claude Code bridge and restores the settings that preceded it.
# Runs on Windows PowerShell 5.1 and PowerShell 7+.

$ErrorActionPreference = 'SilentlyContinue'
$InstallDir = Join-Path $env:LOCALAPPDATA 'HetznerClaudeCode'

$stop = Join-Path $InstallDir 'stop.ps1'
if (Test-Path $stop) { & $stop }

$names = @(
    'HETZNER_API_KEY', 'HETZNER_MODEL', 'HCC_LOCAL_TOKEN',
    'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL',
    'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
    'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'DISABLE_NON_ESSENTIAL_MODEL_CALLS'
)

# The installer saved whatever was configured beforehand.
$previous = $null
$configPath = Join-Path $InstallDir 'config.json'
if (Test-Path $configPath) {
    try { $previous = (Get-Content -Raw $configPath | ConvertFrom-Json).previousEnv } catch { $previous = $null }
}

$restored = 0
foreach ($name in $names) {
    $original = $null
    if ($previous) {
        $property = $previous.PSObject.Properties[$name]
        if ($property) { $original = $property.Value }
    }
    if ([string]::IsNullOrEmpty($original)) {
        [Environment]::SetEnvironmentVariable($name, $null, 'User')
    } else {
        [Environment]::SetEnvironmentVariable($name, $original, 'User')
        $restored++
    }
}

if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }

Write-Host 'Hetzner Claude Code bridge removed.' -ForegroundColor Green
if ($restored -gt 0) {
    Write-Host "Restored $restored setting(s) from before the install." -ForegroundColor Gray
}
Write-Host 'Open a new PowerShell window for the change to take effect.'
