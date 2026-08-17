# One-command server status check: is the scheduled task running, and
# is the server actually answering requests? No elevation needed -- run
# this from any PowerShell prompt on the server box.

$scriptDir = $PSScriptRoot
$configPath = Join-Path $scriptDir "config.bat"
$taskName = "KubunDictateServer"

$port = "50505"
if (Test-Path $configPath) {
    $portMatch = Select-String -Path $configPath -Pattern 'KUBUNDICTATE_PORT=(\d+)' | Select-Object -First 1
    if ($portMatch) { $port = $portMatch.Matches[0].Groups[1].Value }
}

Write-Output "=== KubunDictate server status ==="
Write-Output ""

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Output "Scheduled task '$taskName': $($task.State)"
} else {
    Write-Output "Scheduled task '$taskName': not registered (run install_service.ps1 to set it up)"
}

try {
    $resp = Invoke-WebRequest -Uri "http://localhost:$port/health" -TimeoutSec 3 -UseBasicParsing
    $health = $resp.Content | ConvertFrom-Json
    Write-Output "Health check (http://localhost:$port/health): OK, model '$($health.model)'"
} catch {
    Write-Output "Health check (http://localhost:$port/health): unreachable"
}
