"""Check GitHub Releases for a newer Clicker version, and install it.

Nothing happens behind your back: when a newer release exists the app shows an Update button. On Windows
(the installed app) it downloads the release's installer, checks it against the SHA-256 digest GitHub
publishes for it, then closes Clicker and runs the installer, which opens the new version when it's done.
Elsewhere (macOS, or running from source) it opens the download page.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from . import model

DEFAULT_REPO = "kjbinkley01-bot/t1"
CHECK_EVERY_S = 24 * 3600


def parse_version(text):
    """'v2.10.1' -> (2, 10, 1). Anything unparseable sorts lowest."""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - min(3, len(nums))) if nums else (0, 0, 0)


def is_newer(latest, current=model.APP_VERSION):
    return parse_version(latest) > parse_version(current)


def _get(url, timeout):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"Clicker/{model.APP_VERSION}"}), timeout=timeout)


def latest_release(repo=DEFAULT_REPO, timeout=6):
    """The newest published release: {"tag", "url", "notes", "assets": [{"name", "url", "size", "digest"}]}.
    Raises on network errors."""
    with _get(f"https://api.github.com/repos/{repo}/releases/latest", timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assets = [{"name": a.get("name") or "", "url": a.get("browser_download_url") or "",
               "size": int(a.get("size") or 0), "digest": a.get("digest") or ""}
              for a in data.get("assets") or []]
    return {"tag": data.get("tag_name") or "", "url": data.get("html_url") or "",
            "notes": data.get("body") or "", "assets": assets}


INSTALLER_RE = re.compile(r"^Clicker-Setup.*\.exe$", re.I)


def installer_asset(release):
    """The Windows installer attached to a release, if it has one with a SHA-256 digest to check it by."""
    for a in release.get("assets") or []:
        if INSTALLER_RE.match(a["name"]) and a["url"] and str(a.get("digest", "")).startswith("sha256:"):
            return a
    return None


def install_mode(exe=None, env=None):
    """How this copy of Clicker was installed: "user" (just you), "all" (everyone on the PC), or None when it
    isn't an installed Windows app (macOS, a portable copy, running from source)."""
    if exe is None:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return None
        exe = sys.executable
    env = os.environ if env is None else env
    folder = os.path.normcase(os.path.abspath(os.path.dirname(exe)))

    def inside(var, *rest):
        base = env.get(var)
        if not base:
            return False
        root = os.path.normcase(os.path.abspath(os.path.join(base, *rest)))
        return folder == root or folder.startswith(root + os.sep)
    if inside("LOCALAPPDATA", "Programs"):
        return "user"
    if inside("ProgramFiles") or inside("ProgramW6432") or inside("ProgramFiles(x86)"):
        return "all"
    return None


def can_install(release, mode=None):
    """True when this copy can update itself in place from the release."""
    return (mode or install_mode()) is not None and installer_asset(release) is not None


class DownloadFailed(Exception):
    pass


def download_folder():
    return os.path.join(tempfile.gettempdir(), "clicker-update")


def clean_downloads():
    """Remove installers left from an earlier update (it has finished once the new version is running)."""
    shutil.rmtree(download_folder(), ignore_errors=True)


def download(asset, folder=None, progress=None, stop=None, timeout=20):
    """Download an asset and check its SHA-256 digest. Returns the file's path.
    progress(done_bytes, total_bytes) is called as it goes; stop (a threading.Event) cancels."""
    want = asset["digest"].split(":", 1)[1].lower()
    folder = folder or download_folder()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(asset["name"]))
    part = path + ".part"
    h = hashlib.sha256()
    done = 0
    try:
        with _get(asset["url"], timeout) as resp, open(part, "wb") as f:
            total = int(resp.headers.get("Content-Length") or asset.get("size") or 0)
            while True:
                if stop is not None and stop.is_set():
                    raise DownloadFailed("Cancelled")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if h.hexdigest() != want:
            raise DownloadFailed("The download is damaged (its checksum doesn't match), so it wasn't used. "
                                 "Try again.")
        os.replace(part, path)
        return path
    except DownloadFailed:
        raise
    except Exception as e:
        raise DownloadFailed(f"Could not download the update: {e}")
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def installer_command(path, mode):
    """Run the installer with its progress window only, into the same place as this copy (the installer
    closes Clicker if it's still open and starts the new version at the end)."""
    return [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
            "/ALLUSERS" if mode == "all" else "/CURRENTUSER"]


def run_installer(path, mode):
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # detached, own process group
    subprocess.Popen(installer_command(path, mode), close_fds=True, creationflags=flags)


def due(settings, now=None):
    """True when automatic checks are on and the last one was over a day ago."""
    if not settings.get("check_updates", True):
        return False
    now = time.time() if now is None else now
    return now - float(settings.get("last_update_check") or 0) >= CHECK_EVERY_S


def check_async(settings, callback, force=False):
    """Check on a background thread. callback(result) gets a dict:
    {"newer": bool, "tag": str, "url": str, "notes": str} or {"error": str}.
    """
    if not force and not due(settings):
        return False
    repo = settings.get("update_repo") or DEFAULT_REPO

    def work():
        try:
            rel = latest_release(repo)
            settings["last_update_check"] = time.time()
            tag = rel["tag"]
            callback(dict(rel, newer=bool(tag) and is_newer(tag),
                          skipped=not force and tag == settings.get("skip_update")))
        except urllib.error.HTTPError as e:
            callback({"error": "no version has been published yet" if e.code == 404 else str(e)})
        except Exception as e:  # offline, rate limited...
            callback({"error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return True
