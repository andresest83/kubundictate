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
    # Special-character class is deliberately restricted to characters that
    # are inert in a .bat file's `set VAR=value` line -- config.bat is
    # `call`ed by cmd.exe (start.bat/start_hidden.bat), which parses %...%
    # as variable expansion and ^ as its escape character, silently
    # corrupting anything outside this safe set (confirmed: a generated
    # token with ^ and % came out of `call config.bat` with both characters
    # stripped, desyncing the server's actual token from what every client
    # was told to use).
    $Token.Length -ge 8 -and $Token -cmatch '[A-Za-z]' -and $Token -cmatch '[0-9]' -and $Token -match '[-_.~+]'
}

function New-StrongToken {
    # Guarantees at least one letter, one digit, and one special character
    # rather than relying on chance from a mixed charset. Special charset
    # matches Test-TokenStrength's batch-safe set.
    $letters = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    $digits = [char[]]'23456789'
    $specials = [char[]]'-_.~+'
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

# --- config.bat (server only -- the tray client keeps its own settings
# under %APPDATA%\KubunDictate\, set up on first run of start_tray.bat) ---
if ($mode -eq "server") {
    $writeConfig = $true
    if (Test-Path $configPath) {
        $existingModeMatch = Select-String -Path $configPath -Pattern 'KUBUNDICTATE_MODE=(\w+)' | Select-Object -First 1
        $existingMode = if ($existingModeMatch) { $existingModeMatch.Matches[0].Groups[1].Value } else { $null }

        if ($existingMode -and $existingMode -ne $mode) {
            Write-Output ""
            Write-Warning "This folder is currently configured as a $existingMode (config.bat has KUBUNDICTATE_MODE=$existingMode)."
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
        $port = Read-Host "Server port [50505]"
        if ([string]::IsNullOrWhiteSpace($port)) { $port = "50505" }
        $model = Read-Host "Whisper model [large-v3-turbo]"
        if ([string]::IsNullOrWhiteSpace($model)) { $model = "large-v3-turbo" }
        $language = Read-Host "Force language code, e.g. 'en' (blank = auto-detect)"

        Write-Output ""
        Write-Output "A shared token restricts who can use this server -- optional, off by default. Worth setting if you're not sure who else is on your LAN; skip it for a trusted home network."
        $tokenInput = Read-Host "Shared token (Enter = none, 'generate' for a strong random one, or type your own: 8+ chars with a letter, a number, and one of -_.~+)"
        if ([string]::IsNullOrWhiteSpace($tokenInput)) {
            $token = $null
        } elseif ($tokenInput.Trim().ToLower() -eq "generate") {
            $token = New-StrongToken
        } else {
            while (-not (Test-TokenStrength $tokenInput)) {
                if ([string]::IsNullOrWhiteSpace($tokenInput)) { break }
                $tokenInput = Read-Host "Needs 8+ characters with a letter, a number, and one of -_.~+ (Enter = give up and use no token, 'generate' for a strong random one)"
                if ([string]::IsNullOrWhiteSpace($tokenInput)) { break }
                if ($tokenInput.Trim().ToLower() -eq "generate") {
                    $tokenInput = New-StrongToken
                    break
                }
            }
            $token = if ([string]::IsNullOrWhiteSpace($tokenInput)) { $null } else { $tokenInput }
        }

        if ($token) {
            $tokenFile = Join-Path $scriptDir "server-token.txt"
            "KubunDictate server token, generated $(Get-Date -Format 'yyyy-MM-dd HH:mm')`n$token`n`nEnter this into every client's tray icon (right-click -> Enter new server...) when it asks for a token." |
                Set-Content -Path $tokenFile -Encoding utf8
            Write-Output ""
            Write-Output "===================================================================="
            Write-Output "  TOKEN: $token"
            Write-Output "  Saved to: $tokenFile"
            Write-Output "  Enter this into every client's tray icon (Enter new server...)."
            Write-Output "===================================================================="
            Read-Host "Press Enter once you've noted it down, to continue"
        } else {
            Write-Output "No shared token set -- this server will accept requests from anyone who can reach it on your LAN/Tailscale."
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
        Write-Output "Wrote $configPath"
    } else {
        Write-Output "Keeping existing config.bat."
    }
    Write-Output ""

    # --- Firewall + service + local-client offer + IP summary ---
    $serviceRegistered = $false
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
        Write-Output "Installing client dependencies (including the tray icon libraries) into this same venv..."
        & $venvPython -m pip install -r (Join-Path $scriptDir "requirements-client.txt")

        # Pre-seed the tray client's own settings file so start_tray.bat needs
        # zero setup on this box -- same {"recent": [{url, token}, ...]} shape
        # tray_client.py's save_recent() writes, so it just picks this up.
        $tokenMatch = Select-String -Path $configPath -Pattern 'KUBUNDICTATE_TOKEN=(.+)$' | Select-Object -First 1
        $tokenForSeed = if ($tokenMatch) { $tokenMatch.Matches[0].Groups[1].Value.Trim() } else { $null }
        $localhostUrl = "http://localhost:$portForFirewall"

        $settingsDir = Join-Path $env:APPDATA "KubunDictate"
        $settingsPath = Join-Path $settingsDir "client_settings.json"
        $recent = @()
        if (Test-Path $settingsPath) {
            try {
                $existing = Get-Content $settingsPath -Raw | ConvertFrom-Json
                if ($existing.recent) { $recent = @($existing.recent) }
            } catch {
                $recent = @()
            }
        }
        $recent = @($recent | Where-Object { $_.url -ne $localhostUrl })
        $recent = @(@{ url = $localhostUrl; token = $tokenForSeed }) + $recent
        if ($recent.Count -gt 3) { $recent = $recent[0..2] }

        New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null
        $json = (@{ recent = $recent } | ConvertTo-Json -Depth 5)
        [System.IO.File]::WriteAllText($settingsPath, $json, (New-Object System.Text.UTF8Encoding($false)))

        Write-Output "start_tray.bat is ready to go on this box -- pointed at $localhostUrl, no setup needed."
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
} else {
    Write-Output "Client dependencies installed (including the tray icon libraries)."
    Write-Output "Run start_tray.bat to start dictating -- it asks for your server's LAN or"
    Write-Output "Tailscale address (and its token, if it has one) the first time it runs, and"
    Write-Output "remembers the last 3 you've used."
}

Write-Output ""
Write-Output "=== Done ==="
if ($mode -eq "server") {
    if ($serviceRegistered) {
        Write-Output "Server is registered to start at boot. Start it now with: Start-ScheduledTask -TaskName KubunDictateServer"
    } else {
        Write-Output "Run start.bat to start KubunDictate now."
    }
} else {
    Write-Output "Run start_tray.bat to start dictating."
}
