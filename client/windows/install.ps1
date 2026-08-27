# One-shot client setup: creates the venv and installs the client
# (tray icon) dependencies. Run as `client\windows\install.ps1` from the
# repo root after `git clone`, on any Windows PC -- including the
# server's own box, if you also want to dictate directly there (point it
# at localhost:<port>). No elevation needed.
#
# For the server (the GPU box), run server\install.ps1 instead.

$ErrorActionPreference = "Stop"

# This script sits two levels down (client\windows\). The venv lives at
# the repo root, shared with the server role so a box running both
# (e.g. the GPU box) needs only one copy of it.
$scriptDir = $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
$venvDir = Join-Path $repoRoot "venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

Write-Output "=== KubunDictate client installer ==="
Write-Output ""

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

$requirementsFile = Join-Path $scriptDir "requirements.txt"
Write-Output "Installing dependencies from $(Split-Path -Leaf $requirementsFile)..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed -- see output above."
    exit 1
}
Write-Output ""

# --- server list ---
# The tray client has no text-entry dialog of its own (a Tk box opened
# from a pystray menu callback could never be made to take keyboard
# focus reliably), so the addresses are collected here, where a plain
# console prompt just works, and written straight to the settings file.
$settingsDir = Join-Path $env:APPDATA "KubunDictate"
$settingsPath = Join-Path $settingsDir "client_settings.json"

$writeSettings = $true
if (Test-Path $settingsPath) {
    $overwrite = Read-Host "Server list already exists. Replace it? [y/N]"
    $writeSettings = $overwrite.Trim().ToLower() -eq "y"
}

if ($writeSettings) {
    Write-Output ""
    Write-Output "Where is the server? Use localhost:9505 if this PC is also the server."
    $lan = Read-Host "Server address [localhost:9505]"
    if ([string]::IsNullOrWhiteSpace($lan)) { $lan = "localhost:9505" }

    Write-Output ""
    Write-Output "Optional: a Tailscale address for using this away from home."
    $tailscale = Read-Host "Tailscale address (blank to skip)"

    Write-Output ""
    Write-Output "Only needed if the server was set up with a shared token."
    $token = Read-Host "Shared token (blank = none)"
    $tokenValue = if ([string]::IsNullOrWhiteSpace($token)) { $null } else { $token.Trim() }

    $servers = @(
        [ordered]@{ name = "Local"; url = $lan.Trim(); token = $tokenValue }
    )
    if (-not [string]::IsNullOrWhiteSpace($tailscale)) {
        $servers += [ordered]@{ name = "Tailscale"; url = $tailscale.Trim(); token = $tokenValue }
    }

    if (-not (Test-Path $settingsDir)) {
        New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null
    }
    # Written via .NET rather than Set-Content: Windows PowerShell 5.1's
    # -Encoding utf8 emits a byte-order mark, and Python's json reader
    # rejects a BOM outright -- the client would see the file as empty
    # and report "no servers configured". UTF8Encoding($false) means no BOM.
    $payload = [ordered]@{ servers = $servers; active = "Local" } | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText(
        $settingsPath, $payload, (New-Object System.Text.UTF8Encoding $false)
    )
    Write-Output ""
    Write-Output "Wrote $settingsPath"
} else {
    Write-Output "Keeping the existing server list."
}
Write-Output ""

Write-Output "=== Done ==="
Write-Output "Run client\windows\start_tray.bat to start dictating."
Write-Output "Switch servers, or edit the list, from the tray icon's right-click menu."
