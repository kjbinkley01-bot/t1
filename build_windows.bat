@echo off
cd /d "%~dp0"
echo.
echo === Clicker build ===
echo Installing libraries (first time takes a few minutes)...
python -m pip install --upgrade pip
python -m pip install --upgrade -r requirements-dev.txt
if errorlevel 1 goto fail
echo.
echo Running the tests...
python -m pytest -q
if errorlevel 1 goto testfail
echo.
echo Building Clicker.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Clicker ^
  --icon assets\clicker.ico --add-data "assets\clicker.png;assets" ^
  --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 ^
  --collect-submodules clicker ^
  clicker_app.py
if errorlevel 1 goto fail
echo.
echo Done. Your app is at: %~dp0dist\Clicker.exe
echo To read text from the screen (Read Text steps), also install Tesseract OCR:
echo   https://github.com/UB-Mannheim/tesseract/wiki
pause
exit /b 0
:testfail
echo.
echo The tests failed, so the app was not built. Send the messages above to Claude.
pause
exit /b 1
:fail
echo.
echo Build failed. Take a screenshot of the messages above and send it to Claude.
pause
exit /b 1
