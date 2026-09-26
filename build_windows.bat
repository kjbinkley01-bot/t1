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
python -m PyInstaller --noconfirm --clean Clicker.spec
if errorlevel 1 goto fail
echo.
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
  for /f %%v in ('python -c "from clicker.model import APP_VERSION; print(APP_VERSION)"') do set VER=%%v
  echo Building the installer...
  "%ISCC%" /Q /DAppVersion=%VER% installer\clicker.iss
  if errorlevel 1 goto fail
  echo.
  echo Done. The installer is at: %~dp0dist\Clicker-Setup.exe
) else (
  echo Done. Your app is at: %~dp0dist\Clicker\Clicker.exe
  echo To also build Clicker-Setup.exe, install Inno Setup 6 from https://jrsoftware.org/isdl.php and run this again.
)
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
