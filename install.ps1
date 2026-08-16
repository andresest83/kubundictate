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

function Test-TokenStrength([string]$Token) {
    $Token.Length -ge 8 -and $Token -cmatch '[A-Za-z]' -and $Token -cmatch '[0-9]' -and $Token -match '[^A-Za-z0-9]'
}

function New-StrongToken {
    # Guarantees at least one letter, one digit, and one special character
    # rather than relying on chance from a mixed charset.
    $letters = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    $digits = [char[]]'23456789'
    $specials = [char[]]'!@#%^*-_='
    $all = $letters + $digits + $specials
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()

    function Get-RandomChar($set) {
        $b = New-Object byte[] 1
        $rng.GetBytes($b)
        $set[$b[0] % $set.Length]
    }

    $tokenChars = @((Get-RandomChar $letters), (Get-RandomChar $digits), (Get-RandomChar $specials))
    1..21 | ForEach-Object { $tokenChars += Get-RandomChar $all }
    -join ($tokenChars | Sort-Object { Get-Random })
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
    $existingModeMatch = Select-String -Path $configPath -Pattern 'KUBUNDICTATE_MODE=(\w+)' | Select-Object -First 1
    $existingMode = if ($existingModeMatch) { $existingModeMatch.Matches[0].Groups[1].Value } else { $null }

    if ($existingMode -and $existingMode -ne $mode) {
        Write-Output ""
        Write-Warning "This folder is currently configured as a $existingMode (config.bat has KUBUNDICTATE_MODE=$existingMode)."
        if ($existingMode -eq "server") {
            Write-Output "Want to dictate locally on this same box instead? You don't need to reconfigure it as a client -- run start_local_client.bat, which reuses this server's own settings (install.ps1's server path can set this up for you)."
        }
        $confirmSwitch = Read-Host "Continue and overwrite config.bat to make this box a $mode instead? [y/N]"
        if ($confirmSwitch.Trim().ToLower() -ne "y") {
            Write-Output "Leaving config.bat untouched."
            exit 0
        }
    } else {
        $overwrite = Read-Host "config.bat already exists. Overwrite it? [y/N]"
        $writeConfig = $overwrite.Trim().ToLower() -eq "y"
    }
}

if ($writeConfig) {
    if ($mode -eq "server") {
        $port = Read-Host "Server port [50505]"
        if ([string]::IsNullOrWhiteSpace($port)) { $port = "50505" }
        $model = Read-Host "Whisper model [large-v3-turbo]"
        if ([string]::IsNullOrWhiteSpace($model)) { $model = "large-v3-turbo" }
        $language = Read-Host "Force language code, e.g. 'en' (blank = auto-detect)"

        Write-Output ""
        Write-Output "Without a shared token, anyone who can route to this server on your LAN can use it to transcribe."
        $tokenInput = Read-Host "Shared token (Enter = auto-generate a strong one, type your own: 8+ chars with a letter, a number, and a special character, or 'skip' to leave it off)"
        if ($tokenInput.Trim().ToLower() -eq "skip") {
            $token = $null
        } elseif ([string]::IsNullOrWhiteSpace($tokenInput)) {
            $token = New-StrongToken
        } else {
            while (-not (Test-TokenStrength $tokenInput)) {
                if ($tokenInput.Trim().ToLower() -eq "skip") { break }
                $tokenInput = Read-Host "Needs 8+ characters with a letter, a number, and a special character (Enter = auto-generate, 'skip' to leave it off)"
                if ([string]::IsNullOrWhiteSpace($tokenInput)) {
                    $tokenInput = New-StrongToken
                    break
                }
            }
            $token = if ($tokenInput.Trim().ToLower() -eq "skip") { $null } else { $tokenInput }
        }

        if ($token) {
            Write-Output "Token: $token"
            Write-Output "Copy this into KUBUNDICTATE_TOKEN on every client's config.bat."
        } else {
            Write-Output "Skipping the shared token -- this server will accept requests from anyone who can reach it."
        }

        $lines = @(
            "@echo off",
            "set KUBUNDICTATE_MODE=server",
            "set KUBUNDICTATE_PORT=$port",
            "set KUBUNDICTATE_MODEL=$model"
        )
        if ($token) {
            $lines += "set KUBUNDICTATE_TOKEN=$token"
        }
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
        $token = Read-Host "Shared token (ask whoever set up the server -- leave blank only if they told you it has none)"

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

    $localClientAnswer = Read-Host "Also dictate directly from this box (a local client hitting your own server at localhost)? [y/N]"
    if ($localClientAnswer.Trim().ToLower() -eq "y") {
        Write-Output "Installing client dependencies into this same venv..."
        & $venvPython -m pip install -r (Join-Path $scriptDir "requirements-client.txt")
        $localClientScript = Join-Path $scriptDir "start_local_client.bat"
        if (Test-Path $localClientScript) {
            Write-Output "Run start_local_client.bat on this box to dictate locally."
        } else {
            Write-Warning "start_local_client.bat not found next to this script -- expected it to ship with the repo."
        }
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
