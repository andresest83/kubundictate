@echo off
REM Everything the server needs -- config.bat, server.py -- sits next to
REM this file in server\. The venv is the one exception: it lives at the
REM repo root ("%~dp0..\venv"), shared with the client role so a box that
REM runs both doesn't need two copies of it.
cd /d "%~dp0"
if exist "%~dp0config.bat" call "%~dp0config.bat"
"%~dp0..\venv\Scripts\python.exe" "%~dp0server.py"
pause
