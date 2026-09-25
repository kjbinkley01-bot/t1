"""Turn the Add / Edit Action form's text values into a step and back, without any widgets.

values: the fixed fields, all strings (booleans for cursor_back):
    x, y, action, cursor_back, delay, repeat, comment, label,
    wait_mode (a WAIT_MODES label), wait_target, wait_timeout, wait_poll, wait_conf,
    on_timeout (an ON_TIMEOUT label), wait_goto, retries
detail: {field key: text} for the action's own fields (model.FIELD_SPECS).
"""

from . import model

EMPTY = {
    "x": "", "y": "", "action": "Left Click", "cursor_back": False, "delay": "100", "repeat": "1",
    "comment": "", "label": "", "wait_mode": model.WAIT_LABEL["none"], "wait_target": "",
    "wait_timeout": "30", "wait_poll": "250", "wait_conf": "90", "on_timeout": model.ON_TIMEOUT_LABEL["stop"],
    "wait_goto": "", "retries": str(model.DEFAULT_RETRIES),
}


def form_to_step(values, detail, has_image):
    """Build a step from the form. Raises ValueError with a message for the user."""
    v = dict(EMPTY, **values)
    a = v["action"]
    if a not in model.ACTION_GROUP:
        raise ValueError("Choose an action type.")
    step = {
        "action": a,
        "x": model.parse_int(v["x"], "X", allow_blank=True),
        "y": model.parse_int(v["y"], "Y", allow_blank=True),
        "cursor_back": bool(v["cursor_back"]),
        "delay_ms": model.parse_int(v["delay"] or "0", "Delay", 0),
        "repeat": model.parse_int(v["repeat"] or "1", "Repeat", 1),
        "comment": str(v["comment"]).strip(),
        "label": str(v["label"]).strip(),
    }
    for key, text, _w, kind in model.FIELD_SPECS.get(a, []):
        raw = detail.get(key, model.DEFAULTS.get(key, ""))
        step[key] = model.parse_field(kind, raw, text)
    if a in model.IMAGE_ACTIONS:
        for name in model.step_images(step):
            if not has_image(name):
                raise ValueError(f"Image '{model.image_stem(name)}' is not in this script. Capture or Load it.")
        if not step.get("images"):
            step.pop("images", None)
            step.pop("image_mode", None)
    mode = model.WAIT_ID.get(v["wait_mode"], "none")
    w = {"mode": mode}
    if mode != "none":
        target = str(v["wait_target"]).strip()
        if mode.startswith("image"):
            name = model.image_name(target)
            if not name or not has_image(name):
                raise ValueError("Capture the image to wait for (Watch for).")
            w["image"] = name
            w["confidence"] = model.parse_int(v["wait_conf"], "Match %", 50, 100) / 100.0
        elif mode == "pixel_is":
            w["x"], w["y"], w["color"] = model.parse_pixel_target(target)
            w["tolerance"] = 12
        elif mode == "region_stable":
            w["region"] = model.parse_region(target, "Watch for region")
            w["stable_ms"] = 800
        w["timeout_s"] = model.parse_int(v["wait_timeout"], "Timeout", 0)
        w["poll_ms"] = model.parse_int(v["wait_poll"], "Check every", 20)
        w["on_timeout"] = model.ON_TIMEOUT_ID.get(v["on_timeout"], "stop")
        if w["on_timeout"] in ("retry", "retry_handler"):
            w["retries"] = model.parse_int(v["retries"] or "0", "Retries", 0, 100)
        if w["on_timeout"] == "goto":
            w["goto"] = model.parse_target(v["wait_goto"], "Timeout step")
            if w["goto"] is None:
                raise ValueError("Enter the step number or label to go to when it times out.")
    step["wait"] = w
    err = model.check_step(step)
    if err:
        raise ValueError(err)
    return step


def step_to_form(step):
    """(values, detail) that show this step in the form."""
    detail = {}
    for key, text, _w, kind in model.FIELD_SPECS.get(step["action"], []):
        val = step.get(key)
        detail[key] = model.field_to_text(kind, val, text) if val is not None else model.DEFAULTS.get(key, "")
    v = dict(EMPTY)
    v.update({
        "x": "" if step.get("x") is None else str(step["x"]),
        "y": "" if step.get("y") is None else str(step["y"]),
        "action": step["action"],
        "cursor_back": bool(step.get("cursor_back")),
        "delay": str(step.get("delay_ms", 0)),
        "repeat": str(step.get("repeat", 1)),
        "comment": step.get("comment", ""),
        "label": step.get("label", ""),
    })
    w = step.get("wait") or {}
    mode = w.get("mode", "none")
    v["wait_mode"] = model.WAIT_LABEL.get(mode, model.WAIT_LABEL["none"])
    if mode.startswith("image"):
        v["wait_target"] = w.get("image", "")
        v["wait_conf"] = str(int(round(float(w.get("confidence", 0.9)) * 100)))
    elif mode == "pixel_is":
        v["wait_target"] = f"{w.get('x')}, {w.get('y')}, {w.get('color')}"
    elif mode == "region_stable":
        v["wait_target"] = model.format_region(w.get("region"))
    if mode != "none":
        v["wait_timeout"] = str(w.get("timeout_s", 30))
        v["wait_poll"] = str(w.get("poll_ms", 250))
        v["on_timeout"] = model.ON_TIMEOUT_LABEL.get(w.get("on_timeout", "stop"), model.ON_TIMEOUT_LABEL["stop"])
        v["wait_goto"] = str(w.get("goto") or "")
        v["retries"] = str(w.get("retries", model.DEFAULT_RETRIES))
    return v, detail


WAIT_HINTS = {
    "none": ("Capture", "Runs after the fixed delay. Pick a condition to wait on the screen instead."),
    "image_appears": ("Capture", "Waits until the captured image is visible."),
    "image_vanishes": ("Capture", "Waits until the captured image is gone."),
    "pixel_is": ("Grab", "Enter x, y, #color. Grab fills it from under the cursor after 3 s."),
    "region_stable": ("Draw", "Region x, y, w, h to watch (blank = whole screen)."),
}
