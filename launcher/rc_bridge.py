"""Qt side of the RC page: a QObject registered on the web channel as "rc" (same pattern as rb_bridge.py).

Register it next to the main bridge, two lines in app.py:
    from .rc_bridge import RcBridge
    self.rc = RcBridge(self.win, RcModule(Paths(store.root, ...)))     # RcModule() reads the real paths from the environment
    self.channel.registerObject("rc", self.rc)

The page talks to it through `makeRcClient(channel.objects.rc)` (launcher/web/rc/rc-page.js). Slots take and return
strings; every call runs on a worker thread inside RcModule and answers with the `event` signal, so the window never
waits on a hash, a download or a game start. Only the two file pickers block, because they are dialogs.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from .rc import RcModule


class RcBridge(QObject):
    event = Signal(str)  # one JSON object per event: {"type": "reply"|"task", ...}

    def __init__(self, window, module: RcModule, parent=None):
        super().__init__(parent)
        self.win, self.module = window, module
        self._off = module.subscribe(lambda ev: self.event.emit(json.dumps(ev)))  # emit() is thread-safe: Qt queues it

    @Slot(str, str, str)
    def request(self, rid: str, method: str, params_json: str) -> None:
        try:
            params = json.loads(params_json) if params_json else {}
        except ValueError:
            params = {}
        self.module.call_async(str(rid)[:40], str(method)[:60], params if isinstance(params, dict) else {})

    @Slot(str, result=str)
    def pickFolder(self, title: str) -> str:
        return QFileDialog.getExistingDirectory(self.win, title or "Choose a folder") or ""

    @Slot(str, str, result=str)
    def pickFile(self, title: str, name_filter: str) -> str:
        path, _ = QFileDialog.getOpenFileName(self.win, title or "Choose a file", "", name_filter or "Programs (*.exe)")
        return path or ""

    @Slot(str)
    def openUrl(self, url: str) -> None:
        if url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))

    def shutdown(self) -> None:
        self._off()
        self.module.close()
