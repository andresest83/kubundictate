# One-command server status check: is the scheduled task running, and
# is the server actually answering requests? No elevation needed -- run
# this from any PowerShell prompt on the server box.

$scriptDir = $PSScriptRoot
$configPath = Join-Path $scriptDir "config.bat"
$taskName = "KubunDictateServer"

$port = "9505"
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
    # Get-ScheduledTask silently omits tasks it can't read -- e.g. this
    # one, registered to run as SYSTEM (install_service.ps1) so it
    # can start before login -- instead of erroring, so an empty result
    # here doesn't prove the task is actually missing. schtasks.exe is
    # more honest about *why* it found nothing: "Access is denied" means
    # the task exists but this non-elevated session can't read its state;
    # "cannot find the file specified" means it's genuinely not there.
    $schtasksOutput = & schtasks /query /tn $taskName 2>&1 | Out-String
    if ($schtasksOutput -match "Access is denied") {
        Write-Output "Scheduled task '$taskName': registered (likely running as SYSTEM), but this session can't read its live state -- re-run as Administrator for that, or trust the health check below."
    } else {
        Write-Output "Scheduled task '$taskName': not registered (run server\install_service.ps1 to set it up)"
    }
}

try {
    $resp = Invoke-WebRequest -Uri "http://localhost:$port/health" -TimeoutSec 3 -UseBasicParsing
    $health = $resp.Content | ConvertFrom-Json
    Write-Output "Health check (http://localhost:$port/health): OK, model '$($health.model)'"
} catch {
    Write-Output "Health check (http://localhost:$port/health): unreachable"
}
