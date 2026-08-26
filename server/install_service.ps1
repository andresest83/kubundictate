# Registers KubunDictate's server to start automatically at boot via
# Windows Task Scheduler (runs as SYSTEM, whether or not anyone is
# logged in). Must be run from an elevated (Administrator) PowerShell.
#
# This assumes server\install.ps1 has already been run (config.bat
# present in this folder) -- see README.md.
#
# Note: the task stores the launcher's absolute path, so if the repo is
# moved or the scripts are relocated, re-run this to re-register it --
# otherwise the old path stays registered and the server silently fails
# to start at boot.

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "This script must be run from an elevated (Administrator) PowerShell. Right-click PowerShell -> Run as Administrator, then re-run this script."
    exit 1
}

$taskName = "KubunDictateServer"
$scriptDir = $PSScriptRoot
$launcher = Join-Path $scriptDir "start_hidden.bat"

if (-not (Test-Path $launcher)) {
    Write-Error "start_hidden.bat not found next to this script ($launcher)."
    exit 1
}

$action = New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Output "Registered scheduled task '$taskName' (runs $launcher at startup as SYSTEM)."
Write-Output "Start it now with: Start-ScheduledTask -TaskName $taskName"
Write-Output "Check status with:  server\status.ps1"
Write-Output "Logs land in:       $scriptDir\kubundictate.log"
