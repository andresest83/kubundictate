# Registers KubunDictate's server to start automatically at boot via
# Windows Task Scheduler (runs as SYSTEM, whether or not anyone is
# logged in). Must be run from an elevated (Administrator) PowerShell.
#
# This assumes install_server.ps1 has already been run in this folder
# (config.bat present) -- see README.md.

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "This script must be run from an elevated (Administrator) PowerShell. Right-click PowerShell -> Run as Administrator, then re-run this script."
    exit 1
}

$taskName = "KubunDictateServer"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $scriptDir "start_server_hidden.bat"

if (-not (Test-Path $launcher)) {
    Write-Error "start_server_hidden.bat not found next to this script ($launcher)."
    exit 1
}

$action = New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Output "Registered scheduled task '$taskName' (runs $launcher at startup as SYSTEM)."
Write-Output "Start it now with: Start-ScheduledTask -TaskName $taskName"
Write-Output "Check status with:  status_server.ps1"
Write-Output "Logs land in:       $scriptDir\kubundictate.log"
