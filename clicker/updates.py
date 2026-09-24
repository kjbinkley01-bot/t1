"""Check GitHub Releases for a newer Clicker version.

Nothing is downloaded or installed automatically: when a newer release exists
the app shows a notice that opens its download page.
"""

import json
import re
import threading
import time
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


def latest_release(repo=DEFAULT_REPO, timeout=6):
    """(tag, page url, notes) of the newest published release. Raises on network errors."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"Clicker/{model.APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("tag_name") or "", data.get("html_url") or "", data.get("body") or ""


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
            tag, url, notes = latest_release(repo)
            settings["last_update_check"] = time.time()
            callback({"newer": bool(tag) and is_newer(tag), "tag": tag, "url": url, "notes": notes})
        except Exception as e:  # offline, rate limited, no releases yet...
            callback({"error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return True
