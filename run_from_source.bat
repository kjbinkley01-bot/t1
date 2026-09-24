@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
if /i "%~1"=="console" goto console
rem pythonw runs Clicker without a console, so closing this window doesn't close Clicker.
start "" pythonw clicker_app.py
exit /b 0
:console
rem "run_from_source.bat console" keeps Clicker attached here, to see error messages.
python clicker_app.py
if errorlevel 1 pause
