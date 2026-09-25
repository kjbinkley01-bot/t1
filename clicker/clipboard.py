"""Clipboard text for script steps (Set Clipboard, Copy Clipboard to Variable).

Steps run on a worker thread. The window installs a backend that hands the work to the interface
thread (Qt's clipboard must only be touched there); without one, the OS command line tools are used.
"""

import subprocess
import sys

_backend = None


def set_backend(backend):
    """backend: object with get() -> str and set(text). None goes back to the command line tools."""
    global _backend
    _backend = backend


def get():
    if _backend is not None:
        return _backend.get()
    return _cli_get()


def set(text):  # noqa: A001 (mirrors get)
    if _backend is not None:
        return _backend.set(str(text))
    return _cli_set(str(text))


def _run(cmd, data=None):
    r = subprocess.run(cmd, input=data, capture_output=True, timeout=5)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "replace").strip() or f"{cmd[0]} failed")
    return r.stdout


def _cli_get():
    if sys.platform == "win32":
        out = _run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"])
        return out.decode("utf-8", "replace").rstrip("\r\n")
    if sys.platform == "darwin":
        return _run(["pbpaste"]).decode("utf-8", "replace")
    for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"]):
        try:
            return _run(cmd).decode("utf-8", "replace")
        except (OSError, RuntimeError):
            continue
    raise RuntimeError("No clipboard tool found (install wl-clipboard or xclip)")


def _cli_set(text):
    if sys.platform == "win32":
        _run(["clip"], text.encode("utf-16-le"))
        return
    if sys.platform == "darwin":
        _run(["pbcopy"], text.encode("utf-8"))
        return
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
        try:
            _run(cmd, text.encode("utf-8"))
            return
        except (OSError, RuntimeError):
            continue
    raise RuntimeError("No clipboard tool found (install wl-clipboard or xclip)")
