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

## What's new in 2.3: the Liquid Glass look
Clicker now opens in a new **Liquid Glass** interface built with Qt, following Apple's iOS 26 Liquid Glass kit
(the values are in `assets/liquid_glass_tokens.json`): frosted glass panels over a wallpaper, lit from the top
left, with pill buttons, a tab lens that glides, iOS style switches and glass notices.

* **Wallpapers:** the drop icon (top right) picks Aurora (the kit's gradient), Dusk, Deep Ocean, Mist or
  Blossom, or **your own picture**. Light wallpapers switch the glass to its light mode.
* **All four tabs** (Action Script, Macro Recorder, Screen Triggers, Import Script) are rebuilt in glass
  with every feature of the Classic look.
* **Classic is still there:** the drop icon > *Switch to Classic look*, or start with
  `python clicker_app.py --classic`. From Classic, *Style > Liquid Glass (new look)* switches back. Unsaved
  work comes along either way.
* **Shortcut keys** now live in Settings (the gear icon).
* Icons are Phosphor (MIT) and the font is Inter (OFL), both bundled; Apple's SF Symbols and SF Pro may
  only be used on Apple platforms.

## What's new in 2.2
* **Styles:** click **Style** in the top bar (or use Settings) to switch between **Classic**, **Liquid Glass
  Dark** and **Liquid Glass Light**. Switching keeps your open script, undo history and recording. Glass
  styles have rounded glass panels, glossy buttons with smooth hover, a tab indicator that slides, and
  notices that glide in. **Reduce motion** in the same menu turns animations off.
* **No more clipped text:** sizes follow Windows display scaling (125%, 150%...), table columns are never
  narrower than their headings, and the window can't be shrunk below what its contents need.
* **Smoother:** the cursor and pixel readout moved off the interface thread, fast scripts no longer flood
  the window with updates (the worst stall went from about 2 seconds to 20 ms in testing), long scripts
  redraw only the rows that change, and image searches start where the image was last seen.
* **Safer:** if a button or timer hits an error, the app keeps running and writes the details to
  `errors.log`; unsaved Action Script work is autosaved every minute and offered back after a crash;
  run logs stop recording every step after 20,000 lines so endless loops can't fill the disk.

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
`logs` folder (the newest 40 runs are kept). `errors.log` and `crash.log` there record any errors, and
`autosave.clk` holds unsaved work until you save or close normally. Scripts save as `.clk`, recordings as `.clkrec`, exported
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
