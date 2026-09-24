@echo off
cd /d "%~dp0"
echo.
echo === Clicker v2 build ===
echo Installing libraries (first time takes a few minutes)...
python -m pip install --upgrade pip
python -m pip install --upgrade -r requirements.txt pyinstaller
if errorlevel 1 goto fail
echo.
echo Building Clicker.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Clicker ^
  --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 ^
  --collect-submodules clicker ^
  clicker_app.py
if errorlevel 1 goto fail
echo.
echo Done. Your app is at: %~dp0dist\Clicker.exe
pause
exit /b 0
:fail
echo.
echo Build failed. Take a screenshot of the messages above and send it to Claude.
pause
exit /b 1
