"""Per run log files, with a screenshot saved when a run fails."""

import datetime
import os
import re
import shutil
import subprocess
import sys
import threading

KEEP_RUNS = 40


def logs_dir():
    from . import storage
    path = os.path.join(storage.data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def prune(folder, keep=KEEP_RUNS):
    """Delete the oldest run folders so only `keep` remain."""
    try:
        runs = sorted(d for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d)))
    except OSError:
        return
    for d in runs[:-keep] if keep > 0 else runs:
        shutil.rmtree(os.path.join(folder, d), ignore_errors=True)


def open_folder(path):
    """Show a folder in Explorer / Finder / the file manager."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


class RunLog:
    """Writes a plain text log for one run into its own folder."""

    def __init__(self, name, folder=None, keep=KEEP_RUNS):
        base = folder or logs_dir()
        os.makedirs(base, exist_ok=True)
        prune(base, keep - 1)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(name or "script")).strip("_")[:40] or "script"
        self.dir = os.path.join(base, f"{stamp}_{safe}")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "log.txt")
        self._lock = threading.Lock()
        self._f = open(self.path, "a", encoding="utf-8")
        self.screenshots = []

    def write(self, msg):
        line = f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}  {msg}\n"
        with self._lock:
            if self._f:
                self._f.write(line)
                self._f.flush()

    def screenshot(self, tag="failure", mark=None):
        """Save the whole screen as PNG, outlining `mark` (x, y, w, h) in red if given."""
        try:
            import cv2

            from . import vision
            img, (ox, oy) = vision.capture(None)
            img = img.copy()
            if mark:
                x, y, w, h = (int(v) for v in mark)
                cv2.rectangle(img, (x - ox - 2, y - oy - 2), (x - ox + w + 1, y - oy + h + 1), (40, 40, 230), 3)
            name = f"{tag}_{len(self.screenshots) + 1}.png"
            path = os.path.join(self.dir, name)
            with open(path, "wb") as f:
                f.write(vision.encode_png(img))
            self.screenshots.append(path)
            self.write(f"Screenshot saved: {name}")
            return path
        except Exception as e:  # never let logging break a run
            self.write(f"Could not save screenshot: {e}")
            return None

    def close(self):
        with self._lock:
            if self._f:
                self._f.close()
                self._f = None
