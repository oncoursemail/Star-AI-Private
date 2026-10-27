"""The Qt bridge, with the pretend RC module: a request comes back as a reply event, tasks stream as events."""
import json
import os
import time

import pytest

pytest.importorskip("PySide6.QtCore")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from launcher.rc_bridge import RcBridge  # noqa: E402


def pump(app, seconds, until=None):
    end = time.time() + seconds
    while time.time() < end and not (until and until()):
        app.processEvents()
        time.sleep(0.005)


def test_request_reply_and_task_events_cross_the_bridge(world):
    app = QCoreApplication.instance() or QCoreApplication([])
    mod = world.module(spawn=None)
    bridge = RcBridge(None, mod)
    got = []
    bridge.event.connect(lambda text: got.append(json.loads(text)))

    bridge.request("r1", "settings.get", "")
    pump(app, 5, lambda: any(e["type"] == "reply" for e in got))
    reply = [e for e in got if e["type"] == "reply"][0]
    assert reply["id"] == "r1" and reply["ok"] and reply["result"]["mode"] == "screen"

    bridge.request("r2", "launch.start", json.dumps({"client": "steam", "mode": "screen"}))
    pump(app, 10, lambda: any(e["type"] == "task" and e["task"]["state"] == "done" for e in got))
    states = [e["task"]["state"] for e in got if e["type"] == "task"]
    assert states[0] == "queued" and states[-1] == "done"

    bridge.request("r3", "nope.nothing", "{bad json")
    pump(app, 5, lambda: any(e.get("id") == "r3" for e in got))
    bad = [e for e in got if e.get("id") == "r3"][0]
    assert bad["ok"] is False and bad["error"]["code"] == "bad_request"
    bridge.shutdown()


def test_open_url_only_https(world, monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    opened = []
    monkeypatch.setattr("launcher.rc_bridge.QDesktopServices.openUrl", lambda u: opened.append(u.toString()))
    bridge = RcBridge(None, world.module())
    for url in ("file:///c:/windows/system32/calc.exe", "steam://install/1", "http://example.com", "javascript:1"):
        bridge.openUrl(url)
    bridge.openUrl("https://store.steampowered.com/app/471710/")
    assert opened == ["https://store.steampowered.com/app/471710/"]
