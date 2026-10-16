# Switches the model the server runs (#49): sets KUBUNDICTATE_MODEL in
# config.bat, installs that engine's extra dependencies, restarts the
# server (the old model is unloaded when its process exits), and waits for
# /health to report the new one. Needs an elevated (Administrator)
# PowerShell, same as install_service.ps1, because the scheduled task runs
# as SYSTEM.
#
#   .\server\switch_model.ps1 parakeet-v3
#   .\server\switch_model.ps1 qwen3-asr-1.7b
#   .\server\switch_model.ps1 large-v3-turbo     # any faster-whisper model name
#
# With no argument it shows the current model and the choices.

param([string]$Model)

$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot
$repoRoot = Split-Path -Parent $scriptDir
$venvPython = Join-Path $repoRoot "venv\Scripts\python.exe"
$configPath = Join-Path $scriptDir "config.bat"
$taskName = "KubunDictateServer"

# alias -> extra requirements file (null = the base requirements.txt covers it)
$engines = @{
    "parakeet-v3"    = "requirements-parakeet.txt"
    "qwen3-asr-1.7b" = "requirements-qwen3.txt"
}

function Get-ConfigValue([string]$Name, [string]$Default) {
    if (Test-Path $configPath) {
        $m = Select-String -Path $configPath -Pattern "^set $Name=(.*)$" | Select-Object -First 1
        if ($m) { return $m.Matches[0].Groups[1].Value.Trim() }
    }
    return $Default
}

$current = Get-ConfigValue "KUBUNDICTATE_MODEL" "large-v3-turbo"
$port = Get-ConfigValue "KUBUNDICTATE_PORT" "9505"

if ([string]::IsNullOrWhiteSpace($Model)) {
    Write-Output "Current model: $current"
    Write-Output "Choices: parakeet-v3, qwen3-asr-1.7b, or any faster-whisper model (e.g. large-v3-turbo)"
    Write-Output "Usage:   .\server\switch_model.ps1 <model>"
    exit 0
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "Run this from an elevated (Administrator) PowerShell -- it restarts the server's SYSTEM scheduled task."
    exit 1
}
if (-not (Test-Path $venvPython)) {
    Write-Error "No venv at $venvPython -- run server\install.ps1 first."
    exit 1
}
if (-not (Test-Path $configPath)) {
    Write-Error "No config.bat in $scriptDir -- run server\install.ps1 first."
    exit 1
}

# --- dependencies for the chosen engine ---
$extra = $engines[$Model.ToLower()]
if ($extra) {
    Write-Output "Installing $extra (first time can take several minutes)..."
    & $venvPython -m pip install -r (Join-Path $scriptDir $extra)
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install failed -- model not switched, config.bat untouched."
        exit 1
    }
    if ($Model.ToLower() -eq "parakeet-v3") {
        # onnx-asr may also pull in the CPU-only "onnxruntime". It shares a
        # package folder with onnxruntime-gpu, so the two overwrite each
        # other; remove it and put the GPU files back.
        & $venvPython -m pip uninstall -y onnxruntime | Out-Null
        & $venvPython -m pip install --force-reinstall --no-deps "onnxruntime-gpu<1.24"
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Reinstalling onnxruntime-gpu failed -- model not switched, config.bat untouched."
            exit 1
        }
    }
}

# --- config.bat ---
$lines = @(Get-Content $configPath)
$found = $false
$lines = $lines | ForEach-Object {
    if ($_ -match '^set KUBUNDICTATE_MODEL=') { $found = $true; "set KUBUNDICTATE_MODEL=$Model" } else { $_ }
}
if (-not $found) { $lines += "set KUBUNDICTATE_MODEL=$Model" }
$lines | Set-Content -Path $configPath -Encoding ascii
Write-Output "config.bat: KUBUNDICTATE_MODEL $current -> $Model"

# --- restart ---
if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    Write-Output "No '$taskName' scheduled task, so nothing was restarted. Stop the running server (if any) and start it again with server\start.bat."
    exit 0
}
Write-Output "Restarting the server..."
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
# Stopping the task ends the launcher; make sure the python it started is
# gone too, or it would still hold the port and the old model's VRAM.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'server\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName $taskName

# --- wait for the new model ---
# A first run downloads the weights (GBs), so be generous.
$deadline = (Get-Date).AddMinutes(15)
Write-Output "Waiting for the new model to load (log: $scriptDir\kubundictate.log)..."
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    try {
        $health = (Invoke-WebRequest -Uri "http://localhost:$port/health" -TimeoutSec 3 -UseBasicParsing).Content | ConvertFrom-Json
        if ($health.model -eq $Model) {
            Write-Output "Up: $($health.backend)"
            exit 0
        }
    } catch { }
}
Write-Error "Server did not report model '$Model' within 15 minutes -- check $scriptDir\kubundictate.log."
exit 1
