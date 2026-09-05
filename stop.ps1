# Stops the Hetzner Claude Code bridge.
# Runs on Windows PowerShell 5.1 and PowerShell 7+.

$ErrorActionPreference = 'SilentlyContinue'

$stopped = 0
foreach ($process in Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'") {
    if ($process.CommandLine -like '*HetznerClaudeCode*server.py*') {
        Stop-Process -Id $process.ProcessId -Force
        $stopped++
    }
}

if ($stopped -gt 0) {
    Write-Host "Bridge stopped ($stopped process(es))." -ForegroundColor Green
} else {
    Write-Host 'Bridge is already idle.' -ForegroundColor Gray
}
