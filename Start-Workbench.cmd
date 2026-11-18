@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python
py -3 app.py --open
if errorlevel 1 pause
exit /b
:python
python app.py --open
if errorlevel 1 pause
