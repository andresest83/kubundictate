@echo off
cd /d "%~dp0"
if exist "%~dp0config.bat" call "%~dp0config.bat"
"%~dp0venv\Scripts\python.exe" "%~dp0kubundictate.py" > "%~dp0kubundictate.log" 2>&1