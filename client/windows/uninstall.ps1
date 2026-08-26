# Fully removes the Windows client's local state -- venv, settings, and
# the "Run at startup" Registry entry -- so the next
# client\windows\install.ps1 + client\windows\start_tray.bat is a genuine
# first run. Particularly useful when testing client changes: guarantees
# you're not still running stale code/dependencies from an old venv.
# Doesn't touch anything tracked in git, only local machine state. No
# elevation needed, same as install.ps1.
#
# Skips deleting the venv if this box also runs the server
# (server\config.bat present) -- both roles share the one <repo>\venv
# when run from the same checkout, e.g. on the GPU box itself, and
# deleting it would take the server's dependencies down with it.

# This script sits two levels down (client\windows\). Both the shared
# venv and the server's config.bat are reached from the repo root. That
# config.bat lookup is what guards the shared-venv case, so it must
# resolve to server\config.bat -- if it silently pointed at nothing, the
# guard would never fire and this would delete the server's
# dependencies on the GPU box.
$scriptDir = $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
$venvDir = Join-Path $repoRoot "venv"
$serverConfigPath = Join-Path $repoRoot "server\config.bat"
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

# The server and client installers both default to the same <repo>\venv
# when run from the same checkout (e.g. dictating directly on the GPU
# box) -- deleting it here would also take out the server's
# faster-whisper/CUDA dependencies and break its scheduled task.
# server\config.bat only ever gets written by server\install.ps1, so its
# presence is a reliable signal this venv is shared.
if (Test-Path $serverConfigPath) {
    Write-Output "Removing venv..."
    Write-Output "  Skipping -- server\config.bat is present, meaning this box also runs"
    Write-Output "  the server and this venv is shared with it (both installers default"
    Write-Output "  to <repo>\venv). Deleting it would break the server's scheduled task"
    Write-Output "  too. Settings and the startup registry entry below are always"
    Write-Output "  client-only and safe to remove."
} else {
    Write-Output "Removing venv..."
    if (Test-Path $venvDir) {
        Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
    } else {
        Write-Output "  Not present -- skipping."
    }
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
Write-Output "For a genuine first run, including the server-address/token prompt:"
Write-Output "  client\windows\install.ps1"
Write-Output "  client\windows\start_tray.bat"
