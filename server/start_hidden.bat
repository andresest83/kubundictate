@echo off
REM Same as start.bat but silent, writing to server\kubundictate.log
REM instead of a console -- this is what the boot-time scheduled task
REM runs. The venv lives at the repo root ("%~dp0..\venv"), shared with
REM the client role; everything else sits next to this file.
cd /d "%~dp0"
if exist "%~dp0config.bat" call "%~dp0config.bat"
"%~dp0..\venv\Scripts\python.exe" "%~dp0server.py" > "%~dp0kubundictate.log" 2>&1
