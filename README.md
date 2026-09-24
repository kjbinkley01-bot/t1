# Clicker v2

Auto clicker, macro recorder, screen-aware script runner and screen triggers.

## Build the app (Windows)
1. Unzip this folder somewhere (for example Documents\Clicker2).
2. Close any running copy of Clicker.
3. Double-click `build_windows.bat`. The first build downloads the image libraries and takes a few minutes.
4. Your app is `dist\Clicker.exe`.

To try it without building, double-click `run_from_source.bat`.

## Where things are saved
Settings, hotkeys and trigger rules live in `%APPDATA%\Clicker`.
Scripts save as `.clk`, recordings as `.clkrec`, exported triggers as `.clktrig`.

## Default hotkeys
F6 add action at cursor, F7 start/stop script, F8 emergency stop everything,
F9 start/stop recording, F10 start/stop playback, F11 pause/resume.
All can be reassigned in the app.

See `SCRIPT_FORMAT.md` for the importable script format.
