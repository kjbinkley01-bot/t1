@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements-dev.txt
python -m pytest
pause
