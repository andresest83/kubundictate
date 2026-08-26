# Fully removes the Windows client's local state -- venv, settings, and
# the "Run at startup" Registry entry -- so the next install_client.ps1
# + start_tray.bat is a genuine first run. Particularly useful when
# testing client changes: guarantees you're not still running stale
# code/dependencies from an old venv. Doesn't touch anything tracked in
# git, only local machine state. No elevation needed, same as
# install_client.ps1.

$scriptDir = $PSScriptRoot
$venvDir = Join-Path $scriptDir "venv"
$settingsDir = Join-Path $env:APPDATA "KubunDictate"
$startupKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$startupName = "KubunDictate"

Write-Output "=== KubunDictate client uninstaller ==="
Write-Output ""

Write-Output "Stopping any running instance..."
$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*tray_client.py*" }
if ($running) {
    foreach ($proc in $running) {
        Write-Output "  Stopping PID $($proc.ProcessId)..."
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Output "  Not running -- skipping."
}

Write-Output "Removing venv..."
if (Test-Path $venvDir) {
    Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
} else {
    Write-Output "  Not present -- skipping."
}

Write-Output "Removing settings ($settingsDir)..."
if (Test-Path $settingsDir) {
    Remove-Item -Recurse -Force $settingsDir -ErrorAction SilentlyContinue
} else {
    Write-Output "  Not present -- skipping."
}

Write-Output "Removing 'Run at startup' registry entry, if present..."
if (Get-ItemProperty -Path $startupKey -Name $startupName -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -Path $startupKey -Name $startupName -ErrorAction SilentlyContinue
    Write-Output "  Removed."
} else {
    Write-Output "  Not present -- skipping."
}

Write-Output ""
Write-Output "=== Done ==="
Write-Output "Run install_client.ps1 then start_tray.bat for a genuine first run,"
Write-Output "including the first-run server-address/token prompt."
