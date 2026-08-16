# One-shot setup: creates the venv, installs the right dependencies, and
# configures this machine as a KubunDictate server or client. Run from
# this folder after `git clone`.
#
# Server mode needs an elevated (Administrator) PowerShell -- it
# provisions a firewall rule and can register a startup service. Client
# mode does not.

$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot
$venvDir = Join-Path $scriptDir "venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$configPath = Join-Path $scriptDir "config.bat"

function Test-IsAdmin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

Write-Output "=== KubunDictate installer ==="
Write-Output ""

# --- Mode ---
$modeAnswer = Read-Host "Install as [S]erver or [C]lient?"
switch ($modeAnswer.Trim().ToLower()) {
    { $_ -in @("s", "server") } { $mode = "server" }
    { $_ -in @("c", "client") } { $mode = "client" }
    default {
        Write-Error "Unrecognized answer '$modeAnswer' -- enter 'server' or 'client'."
        exit 1
    }
}
Write-Output "Installing as: $mode"
Write-Output ""

if ($mode -eq "server" -and -not (Test-IsAdmin)) {
    Write-Error "Server setup needs an elevated (Administrator) PowerShell -- it provisions a firewall rule and can register a startup service. Right-click PowerShell -> Run as Administrator, then re-run this script."
    exit 1
}

# --- Python check ---
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python was not found on PATH. Install Python 3.10+ yourself (this script doesn't install it for you), then re-run."
    exit 1
}

# --- venv ---
if (Test-Path $venvPython) {
    Write-Output "venv already exists at $venvDir -- skipping creation."
} else {
    Write-Output "Creating venv..."
    & python -m venv $venvDir
}

$requirementsFile = Join-Path $scriptDir "requirements-$mode.txt"
Write-Output "Installing dependencies from $(Split-Path -Leaf $requirementsFile)..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed -- see output above."
    exit 1
}
Write-Output ""

# --- config.bat ---
$writeConfig = $true
if (Test-Path $configPath) {
    $overwrite = Read-Host "config.bat already exists. Overwrite it? [y/N]"
    $writeConfig = $overwrite.Trim().ToLower() -eq "y"
}

if ($writeConfig) {
    if ($mode -eq "server") {
        $port = Read-Host "Server port [50505]"
        if ([string]::IsNullOrWhiteSpace($port)) { $port = "50505" }
        $model = Read-Host "Whisper model [large-v3-turbo]"
        if ([string]::IsNullOrWhiteSpace($model)) { $model = "large-v3-turbo" }
        $language = Read-Host "Force language code, e.g. 'en' (blank = auto-detect)"

        $lines = @(
            "@echo off",
            "set KUBUNDICTATE_MODE=server",
            "set KUBUNDICTATE_PORT=$port",
            "set KUBUNDICTATE_MODEL=$model"
        )
        if (-not [string]::IsNullOrWhiteSpace($language)) {
            $lines += "set KUBUNDICTATE_LANGUAGE=$language"
        }
        $lines | Set-Content -Path $configPath -Encoding ascii
    } else {
        $serverAddr = Read-Host "Server address, e.g. 192.168.1.50:50505 or a Tailscale IP"
        if ($serverAddr -notmatch ":\d+$") {
            $serverAddr = "${serverAddr}:50505"
        }
        $serverUrl = "http://$serverAddr"
        $token = Read-Host "Shared token, if the server requires one (blank = none)"

        $lines = @(
            "@echo off",
            "set KUBUNDICTATE_MODE=client",
            "set KUBUNDICTATE_SERVER_URL=$serverUrl"
        )
        if (-not [string]::IsNullOrWhiteSpace($token)) {
            $lines += "set KUBUNDICTATE_TOKEN=$token"
        }
        $lines | Set-Content -Path $configPath -Encoding ascii

        Write-Output ""
        Write-Output "Checking $serverUrl/health ..."
        try {
            $resp = Invoke-WebRequest -Uri "$serverUrl/health" -TimeoutSec 3 -UseBasicParsing
            Write-Output "Reachable: $($resp.Content)"
        } catch {
            Write-Warning "Could not reach $serverUrl/health -- double check the address and that the server is running. The config is saved either way."
        }
    }
    Write-Output "Wrote $configPath"
} else {
    Write-Output "Keeping existing config.bat."
}
Write-Output ""

# --- Server-only: firewall + service + IP summary ---
$serviceRegistered = $false
if ($mode -eq "server") {
    $portForFirewall = if ($writeConfig) {
        $port
    } else {
        $existingPort = Select-String -Path $configPath -Pattern 'KUBUNDICTATE_PORT=(\d+)' | Select-Object -First 1
        if ($existingPort) { $existingPort.Matches[0].Groups[1].Value } else { "50505" }
    }

    $ruleName = "KubunDictate Server"
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Program $venvPython -Protocol TCP -LocalPort $portForFirewall -Action Allow | Out-Null
    Write-Output "Firewall rule '$ruleName' created (scoped to $venvPython on TCP port $portForFirewall)."
    Write-Output ""

    $registerAnswer = Read-Host "Register the server as a startup service now (runs at boot, no login required)? [y/N]"
    if ($registerAnswer.Trim().ToLower() -eq "y") {
        & (Join-Path $scriptDir "install_service.ps1")
        $serviceRegistered = $true
    }
    Write-Output ""

    Write-Output "Server IP addresses for client machines:"
    $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1).IPAddress
    if ($lanIp) {
        Write-Output "  This is your Server IP: $lanIp"
    }
    if (Get-Command tailscale -ErrorAction SilentlyContinue) {
        $tsIp = (& tailscale ip -4 2>$null)
        if ($tsIp) {
            Write-Output "  This is your Tailscale IP: $($tsIp.Trim())"
        }
    }
}

Write-Output ""
Write-Output "=== Done ==="
if ($serviceRegistered) {
    Write-Output "Server is registered to start at boot. Start it now with: Start-ScheduledTask -TaskName KubunDictateServer"
} else {
    Write-Output "Run start.bat to start KubunDictate now."
}
