$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*HetznerClaudeCode*server.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host 'Hetzner Claude Code bridge stopped.'