# Clicker script package format (v2)

This describes the files Clicker's **Import Script** tab opens. Share this file with Claude along with a description or screenshots of a task, and Claude can write a package for it.

## File types

| Extension | What it is |
|---|---|
| `.clkpkg` or `.clk` | A zip file containing `script.json` plus an `images/` folder of PNG templates. Clicker saves `.clk`; both open the same way. |
| `.json` | Just the script. Images are looked for in an `images/` folder next to the file, or can be captured afterwards with **Recapture**. |
| `.clkrec` | A raw recording from the Macro Recorder (not a script). |
| `.clktrig` | Exported screen trigger rules. |

You can also paste the JSON straight into **Import Script > Paste script text**.

## script.json

```json
{
  "format": "clicker-script",
  "version": 2,
  "name": "Export orders",
  "description": "Export yesterday's orders from the portal",
  "screen": {"width": 1920, "height": 1080, "scale": 100},
  "settings": {"repeat": 1, "speed": 1.0, "random_delay_ms": 0},
  "inputs": [
    {"name": "report_date", "label": "Report date", "default": "{yesterday}"}
  ],
  "error_handler": 14,
  "steps": [ ... ]
}
```

* `screen`: the display the images were captured on. Clicker warns if the current screen differs.
* `settings.repeat`: 0 loops until stopped.
* `inputs`: values asked for before each run. Use them in text as `{name}`.
* Built in placeholders: `{today}`, `{yesterday}`, `{tomorrow}` (YYYY-MM-DD) and `{time}` (HH:MM).
* `error_handler`: step number jumped to when a wait uses `"on_timeout": "handler"`.
* Step numbers everywhere are **1 based**.

## Step fields shared by every action

```json
{
  "action": "Left Click",
  "x": 640, "y": 410,
  "cursor_back": false,
  "delay_ms": 100,
  "repeat": 1,
  "comment": "Open first order",
  "wait": {"mode": "none"}
}
```

Order of execution: **wait** (if any), then **delay_ms**, then the action **repeat** times, then cursor back.

### wait (screen-aware timing)

| mode | extra fields |
|---|---|
| `none` | |
| `image_appears` / `image_vanishes` | `image`, optional `region` [x, y, w, h], `confidence` (0.5 to 1.0, default 0.9) |
| `pixel_is` | `x`, `y`, `color` "#RRGGBB", `tolerance` (0 to 255, default 12) |
| `region_stable` | optional `region`, `stable_ms` (how long nothing may change) |

Common fields: `timeout_s` (default 30), `poll_ms` (default 250), `on_timeout`:
`stop`, `skip`, `retry` (3 attempts), `goto` (with `"goto": step`), `handler`.

## Actions

**Mouse** (X and Y optional for clicks and scrolls; blank means the current cursor position):
`Left Click`, `Right Click`, `Middle Click`, `Double Click`, `Double Right Click`, `Triple Click`,
`Ctrl + Click`, `Shift + Click`, `Alt + Click`, `Ctrl + Shift + Click`, `Ctrl + Alt + Click`,
`Shift + Right Click`, `Ctrl + Right Click`, `X1 Button Click`, `X2 Button Click`,
`Begin Dragging`, `End Dragging`, `Begin Right Dragging`, `End Right Dragging` (X and Y required),
`Move Mouse` (X and Y required), `Move Mouse by Offset` (X, Y are the offset),
`Move Mouse by Angle` (X = degrees, 0 is right and 90 is up; Y = distance),
`Scroll Up`, `Scroll Down`, `Scroll Left`, `Scroll Right` (`amount` = notches),
`Save Cursor Location`, `Restore Cursor Location`.

**Keyboard**:
`Type Text` (`text`), `Send Keystroke` (`keys`, e.g. `enter`, `tab`, `f5`),
`Hot Key` (`keys`, e.g. `ctrl+s`, `alt+tab`, `win+d`), `Key Down` / `Key Up` (`keys`).

**Screen** (all take `image`, optional `region`, `confidence`):
* `Click Image`: waits up to `timeout_s` (default 10) for the image, then clicks its center plus X/Y offset. `button`: `left`, `right`, `double`, `middle`.
* `Wait for Image`, `Wait for Image to Vanish`: `timeout_s`.
* `If Image Found`, `If Image Not Found`: checks once. `goto` (when true) and `else_goto` (when false); leave either out to continue.
* `Wait for Pixel Color`: X, Y, `color`, `tolerance`, `timeout_s`.
* `If Pixel Color`: X, Y, `color`, `tolerance`, `goto`, `else_goto`.
* `Wait for Screen to Settle`: optional `region`, `stable_ms`, `timeout_s`.

When a screen action can't find its target in time, the step's `wait.on_timeout` policy decides what happens (default: stop).

**Flow**:
`Delay` (`ms`), `Random Delay` (`min_ms`, `max_ms`), `Go to Step` (`goto`),
`Loop Back` (`goto`, `times`), `Run Script File` (`file`, full path),
`Show Notification` (`message`), `Beep`, `Show Desktop`, `Stop Script`.

## Image names

`"image": "export_button"` refers to `images/export_button.png` inside the package. The `.png` is optional in the JSON.
Templates should be tight crops of something that looks the same every time (a button, an icon, a heading), captured at the same display scaling the script will run on.

## Example

```json
{
  "format": "clicker-script", "version": 2, "name": "Retry until saved",
  "inputs": [{"name": "file_name", "label": "File name", "default": "report_{today}"}],
  "steps": [
    {"action": "Click Image", "image": "export_button", "timeout_s": 15, "delay_ms": 0,
     "wait": {"mode": "none", "on_timeout": "stop"}},
    {"action": "Wait for Pixel Color", "x": 1540, "y": 96, "color": "#2E7D32", "tolerance": 20,
     "timeout_s": 120, "delay_ms": 0},
    {"action": "If Image Found", "image": "error_dialog", "goto": 7, "delay_ms": 0},
    {"action": "Hot Key", "keys": "ctrl+s", "delay_ms": 200},
    {"action": "Type Text", "text": "{file_name}", "delay_ms": 0,
     "wait": {"mode": "image_appears", "image": "save_dialog", "timeout_s": 20, "on_timeout": "stop"}},
    {"action": "Send Keystroke", "keys": "enter", "delay_ms": 150},
    {"action": "Show Notification", "message": "Finished", "delay_ms": 0}
  ]
}
```
