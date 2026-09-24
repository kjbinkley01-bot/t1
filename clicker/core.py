"""Pieces shared by the Classic (Tk) and Liquid Glass (Qt) windows that don't touch widgets."""

import threading

from . import inputs, vision


class Ctx:
    """Thread-safe bridge the trigger engine uses to reach the running job."""

    def __init__(self, app):
        self.app = app

    def _job(self):
        j = self.app.job
        return j if j is not None and j.running else None

    def script_running(self):
        return self._job() is not None

    def hold(self):
        j = self._job()
        if j:
            j.hold()
            self.app._held_job = j

    def release(self):
        j = getattr(self.app, "_held_job", None)
        if j:
            j.release()
            self.app._held_job = None

    def pause(self):
        j = self._job()
        if j:
            j.pause()

    def resume(self):
        j = self._job()
        if j:
            j.resume()

    def rewind(self, n):
        j = self._job()
        if j:
            j.rewind(n)

    def stop_all(self):
        self.app.post("app", "stop_all", None)

    def run_script(self, path):
        self.app.post("app", "run_script", path)


class CursorSampler:
    """Reads the cursor position and the pixel under it on a background thread.

    Grabbing the screen can take tens of milliseconds on Windows; doing it on
    the UI thread made the whole window stutter, especially while resizing.
    """

    def __init__(self, post, interval=0.12):
        self.post = post
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._main, daemon=True, name="cursor-sampler")

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _main(self):
        last = None
        while not self.stop_event.wait(self.interval):
            try:
                x, y = inputs.position()
                hexc = vision.rgb_hex(vision.pixel(x, y))
            except Exception:
                continue
            if (x, y, hexc) != last:
                last = (x, y, hexc)
                self.post("app", "cursor", last)
        vision.release_thread()


# events where only the newest one matters; older ones are dropped when the queue backs up
COALESCE = {("script", "step"), ("script", "log"), ("script", "state"), ("script", "run"),
            ("script", "highlight"), ("app", "cursor"), ("trigger", "highlight")}


def coalesce(batch):
    """Drop superseded updates: keep only the newest of each COALESCE kind, in order."""
    last = {}
    for i, (source, kind, _p) in enumerate(batch):
        if (source, kind) in COALESCE:
            last[(source, kind)] = i
    return [item for i, item in enumerate(batch) if (item[0], item[1]) not in COALESCE or last[(item[0], item[1])] == i]
