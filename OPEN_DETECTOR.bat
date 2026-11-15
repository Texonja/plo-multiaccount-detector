@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 goto console
start "" pythonw "%~dp0PLO_Detector.pyw"
exit /b
:console
py -3 "%~dp0PLO_Detector.pyw"
if errorlevel 1 pause
