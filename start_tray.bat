@echo off
REM Launches the tray client with no console window (pythonw.exe) and
REM detached from this batch file via `start`, so running this from a
REM terminal returns your prompt immediately instead of blocking until
REM the tray app is quit. Settings (recent servers + tokens) live in
REM %APPDATA%\KubunDictate\ -- prompts for a server on first run. See
REM README.md "Client" section.
cd /d "%~dp0"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0tray_client.py"
