@echo off
REM Launches the tray client with no console window (pythonw.exe) and
REM detached from this batch file via `start`, so running this from a
REM terminal returns your prompt immediately instead of blocking until
REM the tray app is quit. Settings (recent servers + tokens) live in
REM %APPDATA%\KubunDictate\ -- prompts for a server on first run. See
REM README.md "Set up a client" section.
REM
REM This file sits two levels down (client\windows\): tray_client.py is
REM one level up in client\, and the venv is at the repo root, shared
REM with the server role.
cd /d "%~dp0.."
start "" "%~dp0..\..\venv\Scripts\pythonw.exe" "%~dp0..\tray_client.py"
