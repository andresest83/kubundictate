# One-shot client setup: creates the venv and installs the client
# (tray icon) dependencies. Run from this folder after `git clone`, on
# any Windows PC -- including the server's own box, if you also want
# to dictate directly there (point it at localhost:<port>). No
# elevation needed.
#
# For the server (the GPU box), run install_server.ps1 instead.

$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot
$venvDir = Join-Path $scriptDir "venv"
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

$requirementsFile = Join-Path $scriptDir "requirements-client.txt"
Write-Output "Installing dependencies from $(Split-Path -Leaf $requirementsFile)..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed -- see output above."
    exit 1
}
Write-Output ""

Write-Output "=== Done ==="
Write-Output "Run start_tray.bat to start dictating -- it asks for your server's LAN or"
Write-Output "Tailscale address (localhost:<port> if this is the server's own box, and its"
Write-Output "token, if it has one) the first time it runs, and remembers the last 3 you've used."
