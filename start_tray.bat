@echo off
REM Launches the tray client with no console window (pythonw.exe). Settings
REM (recent servers + tokens) live in %APPDATA%\KubunDictate\ -- prompts
REM for a server on first run. See README.md "Client" section.
cd /d "%~dp0"
"%~dp0venv\Scripts\pythonw.exe" "%~dp0tray_client.py"
