# Clicker

Auto clicker, macro recorder, screen-aware script runner and screen triggers for Windows and macOS.

## Build the app (Windows)
1. Unzip this folder somewhere (for example Documents\Clicker).
2. Close any running copy of Clicker.
3. Double-click `build_windows.bat`. It installs the libraries, runs the tests, then builds.
   The first build takes a few minutes.
4. Your app is `dist\Clicker.exe`.

To try it without building, double-click `run_from_source.bat`.

**Read Text** steps read words and numbers off the screen with Tesseract OCR. Install it once from
https://github.com/UB-Mannheim/tesseract/wiki (keep the default install folder). Settings shows whether
Clicker can find it.

## Build the app (macOS)
Run `./build_mac.sh`, then grant `dist/Clicker.app` Accessibility, Input Monitoring and Screen Recording
in System Settings > Privacy & Security. For Read Text: `brew install tesseract`.

## What's new in 2.1
* **Editor:** Undo / Redo, select several steps, copy / cut / paste steps (also between scripts, images
  included), drag rows to reorder, and step **labels** to jump to instead of numbers. Moving steps keeps
  numbered jumps pointing at the same step.
* **Logic:** variables (`Set`, `Increment`, `If Variable`), `While ... End While` loops, subroutines
  (`Call Subroutine` / `Return`) and `Read Text` (OCR into a variable).
* **Reliability:** retry counts, "retry, then error handler", restart the script after a failure, image
  matching that copes with display scaling, and a log of every run with a screenshot when it fails
  (Run Logs button).
* **Tests:** `run_tests.bat` or `python -m pytest`. They use a fake screen, mouse and keyboard, so nothing
  is clicked for real.
* **Updates:** Clicker checks GitHub once a day for a newer release and shows a notice with the download
  link (turn it off in Settings).

## Keyboard shortcuts in the step list
Ctrl+Z undo, Ctrl+Y or Ctrl+Shift+Z redo, Ctrl+C / Ctrl+X / Ctrl+V copy, cut, paste, Ctrl+D duplicate,
Ctrl+A select all, Delete delete, Alt+Up / Alt+Down move. Drag a row to move it.

## Where things are saved
Settings, hotkeys and trigger rules live in `%APPDATA%\Clicker` (`~/.clicker` on macOS), run logs in its
`logs` folder (the newest 40 runs are kept). Scripts save as `.clk`, recordings as `.clkrec`, exported
triggers as `.clktrig`.

## Default hotkeys
F6 add action at cursor, F7 start/stop script, F8 emergency stop everything,
F9 start/stop recording, F10 start/stop playback, F11 pause/resume.
All can be reassigned in the app.

## Releasing a new version
1. Change `APP_VERSION` in `clicker/model.py` (for example to `2.2.0`) and commit.
2. Push a tag with the same number: `git tag v2.2.0 && git push origin v2.2.0`.
3. GitHub Actions runs the tests, builds the Windows and macOS apps and publishes a release. Every
   installed copy of Clicker then sees the update within a day.

See `SCRIPT_FORMAT.md` for the importable script format.
