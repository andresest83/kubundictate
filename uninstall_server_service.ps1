# Removes the KubunDictateServer scheduled task created by
# install_server_service.ps1. Must be run from an elevated
# (Administrator) PowerShell.

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "This script must be run from an elevated (Administrator) PowerShell. Right-click PowerShell -> Run as Administrator, then re-run this script."
    exit 1
}

$taskName = "KubunDictateServer"

if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    Write-Output "No scheduled task named '$taskName' found -- nothing to do."
    exit 0
}

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false

Write-Output "Removed scheduled task '$taskName'."
Write-Output "Note: this does not kill an already-running server process -- stop it manually if one is still running."
