#!/bin/sh
cd "$(dirname "$0")"
python3 -m pip install --upgrade -r requirements.txt pyinstaller || exit 1
python3 -m PyInstaller --noconfirm --clean --windowed --name Clicker \
  --hidden-import pynput.keyboard._darwin --hidden-import pynput.mouse._darwin \
  --collect-submodules clicker clicker_app.py || exit 1
echo "Done: dist/Clicker.app"
echo "Grant it Accessibility, Input Monitoring and Screen Recording in System Settings > Privacy & Security."
