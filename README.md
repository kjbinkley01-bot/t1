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

## What's new in 2.6: background mode in every tab
The **Run in** window choice from the Action Script is now in the other tabs too:

* **Macro Recorder:** click **Run in** (top right) and pick a window. Record by using that window normally.
  Positions are saved relative to the window, and clicks outside it (like stopping on Clicker) are left out.
  **Play Recording** then sends everything to that window, so your mouse and keyboard stay free. It starts
  after half a second instead of 2 s, since you don't need to switch windows.
  * A recording made on the whole screen can also play in a window: it's lined up with where the window is now.
  * A recording made in a window can still play on the whole screen, at that window's current position.
  * The window is saved in the `.clkrec` file and comes back when you open it. **Convert to Action Script**
    brings it along, so the script runs in the same window.
* **Screen Triggers:** **Watch** (top of the Rules list) picks the window all rules watch. Image and pixel
  checks read that window's own picture, even while it's covered. Clicks and keys go to it. **Test**, **Grab**,
  **Draw** and **Capture** use window positions. If the window closes, monitoring waits and picks it up
  again when it's back.
* **Import Script:** the **Run in** button shows the window saved in the script and lets you change it
  before you run it.

## What's new in 2.5: step progress and smoother motion
* **Step progress:** while a script runs, the current step shows how long until the next one. A glass fill
  sweeps across the row with a bright leading edge, and the Delay column counts down (`1.6s`). Delays count
  down exactly; screen waits show how much of their time limit is used (`≤8s`) and vanish as soon as the
  screen matches. Pausing freezes the bar. Pauses shorter than 0.15 s aren't shown, so fast scripts stay calm.
* **Tabs slide sideways:** switching tabs slides the page left or right, following the tab order, while the
  wallpaper stays put.
* **Smooth resizing:** the wallpaper is drawn once at screen size and fitted to the window, so the gradient
  stretches smoothly when you drag the window bigger quickly, with no smeared line at the edge.

## What's new in 2.4: background mode (Windows)
Run a script **inside one window** while you keep using your mouse and computer. In the Action Script tab,
click **Run in: Whole screen** and pick the window (from the list, or by clicking it).

* **Background messages** (default): clicks, keys, typing, scrolling and drags are sent straight to the
  window. Nothing on your desktop moves. Works with most normal apps.
* **Quick switch**: for apps that ignore those messages (apps and games that read the physical mouse), the
  window comes forward for a moment, gets real input, and your window and cursor are put right back.
* Image checks, pixel checks and Read Text look at **the window's own picture**, so they keep working while
  it's covered by other windows. **Test capture** in the dialog shows exactly what Clicker sees.
* Positions are measured from the window's top left corner, so moving the window doesn't break the script.
  Pick, Grab, Draw and Capture switch to window positions automatically.
* If the window is minimized, Clicker can restore it **behind** your other windows (most apps stop drawing
  while minimized, so they can't be seen or clicked there).
* The window is saved with the script (`settings.target`), and the Classic look runs such scripts too.

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
