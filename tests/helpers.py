"""Small builders shared by the runner tests."""

from clicker import model
from clicker.runner import Runner
from clicker.storage import AssetStore


def S(action, **kw):
    """A step with no delay, so tests run fast."""
    st = {"action": action, "delay_ms": 0}
    st.update(kw)
    return st


def script(*steps, **top):
    data = {"name": top.pop("name", "test"), "steps": list(steps)}
    data.update(top)
    return model.normalize_script(data)


def run(sc, assets=None, log_dir=None, **kw):
    """Run a script synchronously. Returns (runner, events)."""
    events = []
    kw.setdefault("speed", 50)
    r = Runner(sc, assets or AssetStore(), lambda k, p=None: events.append((k, p)),
               log_dir=log_dir, save_log=log_dir is not None, **kw)
    r._main()
    return r, events


def logs(events):
    return [p for k, p in events if k == "log"]
