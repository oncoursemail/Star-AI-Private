"""The social/game packages' HostAgent protocol (star/social/activity.py) on top of STAR Home's Executor.

Every call goes through Executor.do, so the owner's STOP, the action log and the dry run apply to it. In a dry run
nothing happens on screen, so `foreground_title` answers with the window she last "focused": the social activities
then walk through their steps and the log shows what she would have done.
"""
from __future__ import annotations

from pathlib import Path


class HostAdapter:
    def __init__(self, executor) -> None:
        self.executor = executor
        self._front = ""

    def focus_window(self, title: str) -> bool:
        result = self.executor.do("focus_window", {"title": title})
        if result.ok:
            self._front = title
        return result.ok

    def foreground_title(self) -> str:
        if self.executor.dry_run:
            return self._front
        result = self.executor.do("foreground_title")
        return result.text if result.ok else ""

    def screenshot(self) -> Path:
        result = self.executor.do("screenshot")
        if not result.ok or not result.path:
            raise RuntimeError(result.text)
        return Path(result.path)

    def key(self, combo: str) -> None:
        self.executor.do("key", {"keys": combo})

    def type_text(self, text: str) -> None:
        self.executor.do("type_text", {"text": text})

    def hold(self, key: str, seconds: float) -> None:
        self.executor.do("hold", {"key": key, "seconds": seconds})

    def open_uri(self, uri: str) -> None:
        self.executor.do("launch", {"target": uri})

    def click(self, x: int, y: int) -> None:
        self.executor.do("click", {"x": int(x), "y": int(y)})
