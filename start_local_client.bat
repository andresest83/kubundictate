@echo off
REM Runs a local client on this same box, pointed at its own server on
REM localhost -- for a GPU box that also wants hotkey dictation directly,
REM without a separate client machine. Reuses config.bat's
REM KUBUNDICTATE_PORT and KUBUNDICTATE_TOKEN (if set); only MODE and
REM SERVER_URL are overridden here. Requires client dependencies to
REM already be installed in this venv (install.ps1's server path offers
REM this) and config.bat to already have KUBUNDICTATE_MODE=server set.
cd /d "%~dp0"
if exist "%~dp0config.bat" call "%~dp0config.bat"
if not defined KUBUNDICTATE_PORT set KUBUNDICTATE_PORT=50505
set KUBUNDICTATE_MODE=client
set KUBUNDICTATE_SERVER_URL=http://localhost:%KUBUNDICTATE_PORT%
"%~dp0venv\Scripts\python.exe" "%~dp0kubundictate.py"
pause
