"""Windows notifications on her PC -> "a message is waiting" events (star.home.attention.Incoming).

Two sources read the toasts Windows shows (the Action Center history), so no app needs a bot token or an API:
  WpnDatabaseSource  polls %LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db (a read-only copy of the
                     file and its WAL; table Notification, XML payload, ArrivalTime as a Windows FILETIME). Schema
                     checked against a real Windows 11 PC; the toast text of Discord itself was not seen.
  WinRTToastSource   UserNotificationListener through the `winsdk` package (needs Settings > Privacy > Notifications
                     access); preferred when available, it has no file copy.
parse_toast() turns a Discord/Roblox toast into an Incoming. The Discord formats are patterns, not captured samples:
a DM toast has the sender as its title, a server mention "Name (#channel, Server)", a call "... is calling" or
"Incoming call". NotificationWatcher polls a source and feeds the inbox; the first poll only learns what is already
there, so old unread toasts are left to the periodic Discord check.
"""
from __future__ import annotations

from dataclasses import dataclass
import glob
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from typing import Callable, Protocol
import xml.etree.ElementTree as ET

from .attention import Incoming

DEFAULT_APPS = ("discord", "roblox")
_CALL = re.compile(r"\b(?:incoming\s+(?:voice\s+|video\s+)?call|is\s+calling(?:\s+you)?|calling\s+you|started\s+a\s+(?:voice\s+)?call|"
                   r"wants\s+to\s+(?:voice\s+)?call)\b", re.I)
_IS_CALLING = re.compile(r"^(?P<who>.{1,60}?)\s+is\s+calling\b", re.I)
_GENERIC_TITLE = re.compile(r"^(?:incoming\s+(?:voice\s+|video\s+)?call|discord|call)$", re.I)
_SERVER = re.compile(r"^(?P<who>.+?)\s*\((?:#|.*#)", re.S)
FILETIME_EPOCH_DIFF = 11644473600          # seconds between 1601-01-01 and 1970-01-01


@dataclass(frozen=True)
class Toast:
    id: str
    app: str                # the app's id or display name
    title: str
    body: str
    at: float               # epoch seconds


def parse_toast(toast: Toast, apps: tuple[str, ...] = DEFAULT_APPS, ring_s: float = 45.0) -> Incoming | None:
    app = toast.app.lower()
    platform = next((a for a in apps if a in app), "")
    if not platform:
        return None
    title, body = toast.title.strip(), toast.body.strip()
    if platform == "discord":
        joined = f"{title} {body}"
        if _CALL.search(joined):
            who = ""
            for line in (title, body):
                found = _IS_CALLING.match(line)
                if found:
                    who = found.group("who").strip()
                    break
            if not who:
                who = title if title and not _GENERIC_TITLE.match(title) else body
            return Incoming("call", "discord", who[:60], "", at=toast.at, ring_s=ring_s)
        server = _SERVER.match(title)
        if server:
            return Incoming("mention", "discord", server.group("who").strip()[:60], body[:300], at=toast.at)
        if title:
            return Incoming("dm", "discord", re.sub(r"\s*\(.*\)\s*$", "", title)[:60], body[:300], at=toast.at)
        return None
    return Incoming("dm", platform, title[:60], body[:300], at=toast.at) if title else None


class ToastSource(Protocol):
    def poll(self) -> list[Toast]: ...


def toast_from_xml(xml_text: str) -> tuple[str, str]:
    """(title, body) of a toast payload: the first <text> is the title, the rest is the body."""
    try:
        root = ET.fromstring(xml_text.strip().lstrip("﻿"))
    except ET.ParseError:
        return "", ""
    texts = [(node.text or "").strip() for node in root.iter("text") if (node.text or "").strip()]
    return (texts[0] if texts else ""), " ".join(texts[1:])


class WpnDatabaseSource:
    """Toasts from the Windows notification database (read-only copy, so Windows is never blocked)."""

    def __init__(self, path: str | Path | None = None, *, apps: tuple[str, ...] = DEFAULT_APPS) -> None:
        base = Path(path) if path else Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Notifications")) / "wpndatabase.db"
        self.path, self.apps = base, tuple(a.lower() for a in apps)

    def poll(self) -> list[Toast]:
        if not self.path.exists():
            return []
        folder = Path(tempfile.mkdtemp(prefix="star-wpn-"))
        try:
            for name in glob.glob(str(self.path) + "*"):            # the database and its -wal and -shm files
                shutil.copy(name, folder)
            db = sqlite3.connect(str(folder / self.path.name))
            try:
                rows = db.execute(
                    "SELECT n.Id, h.PrimaryId, n.Payload, n.ArrivalTime FROM Notification n "
                    "JOIN NotificationHandler h ON h.RecordId = n.HandlerId WHERE n.Type = 'toast' "
                    "ORDER BY n.ArrivalTime DESC LIMIT 60").fetchall()
            finally:
                db.close()
        except (OSError, sqlite3.Error):
            return []
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        out = []
        for ident, app, payload, arrival in rows:
            if not any(a in str(app).lower() for a in self.apps):
                continue
            text = payload.decode("utf-8", errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload or "")
            title, body = toast_from_xml(text)
            if title or body:
                out.append(Toast(str(ident), str(app), title, body, (int(arrival or 0) / 10_000_000) - FILETIME_EPOCH_DIFF))
        return out


class WinRTToastSource:  # pragma: no cover - needs Windows, the winsdk package and notification access
    def __init__(self, apps: tuple[str, ...] = DEFAULT_APPS) -> None:
        from winsdk.windows.ui.notifications.management import UserNotificationListener, UserNotificationListenerAccessStatus
        self._listener = UserNotificationListener.current
        self._allowed = UserNotificationListenerAccessStatus.ALLOWED
        self.apps = tuple(a.lower() for a in apps)

    def available(self) -> bool:
        import asyncio
        try:
            return asyncio.run(self._listener.request_access_async()) == self._allowed
        except Exception:
            return False

    def poll(self) -> list[Toast]:
        import asyncio
        from winsdk.windows.ui.notifications import KnownNotificationBindings, NotificationKinds

        async def read():
            return await self._listener.get_notifications_async(NotificationKinds.TOAST)

        try:
            notes = asyncio.run(read())
        except Exception:
            return []
        out = []
        for note in notes:
            app = note.app_info.display_info.display_name
            if not any(a in app.lower() for a in self.apps):
                continue
            binding = note.notification.visual.get_binding(KnownNotificationBindings.get_toast_generic())
            texts = [t.text for t in binding.get_text_elements()] if binding else []
            stamp = note.creation_time.timestamp() if hasattr(note.creation_time, "timestamp") else time.time()
            out.append(Toast(str(note.id), app, texts[0] if texts else "", " ".join(texts[1:]), stamp))
        return out


def best_source(apps: tuple[str, ...] = DEFAULT_APPS) -> ToastSource:  # pragma: no cover - reads the real PC
    try:
        source = WinRTToastSource(apps)
        if source.available():
            return source
    except Exception:
        pass
    return WpnDatabaseSource(apps=apps)


class NotificationWatcher:
    """Polls a source; every new toast from a watched app goes into the inbox as an Incoming."""

    def __init__(self, source: ToastSource, inbox, *, apps: tuple[str, ...] = DEFAULT_APPS, ring_s: float = 45.0,
                 clock: Callable[[], float] = time.time, on_toast: Callable[[Toast, Incoming | None], None] | None = None):
        self.source, self.inbox, self.apps, self.ring_s, self.clock = source, inbox, apps, ring_s, clock
        self.on_toast = on_toast or (lambda toast, incoming: None)
        self._seen: set[str] = set()
        self._primed = False
        self._stop = threading.Event()

    def tick(self) -> list[Incoming]:
        toasts = self.source.poll()
        fresh = [t for t in toasts if t.id not in self._seen]
        self._seen.update(t.id for t in toasts)
        if len(self._seen) > 2000:
            self._seen = {t.id for t in toasts}
        if not self._primed:
            self._primed = True
            return []
        found = []
        for toast in sorted(fresh, key=lambda t: t.at):
            incoming = parse_toast(toast, self.apps, self.ring_s)
            self.on_toast(toast, incoming)
            if incoming is not None:
                self.inbox.add(incoming)
                found.append(incoming)
        return found

    def run(self, interval_s: float = 2.0) -> None:  # pragma: no cover - the long-running thread
        while not self._stop.wait(interval_s):
            try:
                self.tick()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
