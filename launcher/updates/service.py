"""What the launcher's Bridge calls. Qt-free: every method returns plain dicts and never raises, so a slot can
`json.dumps` the result. Wiring into launcher/app.py is three slots (see docs/agents/metallic-px-updater-site-20261026.md).

Settings used (added to the launcher's settings.json):
    "updates": {"url": "", "channel": "stable", "layout": "tree", "auto": "ask"}
`url` is empty until the owner has a server; the launcher then says "updates not set up" instead of guessing.
"""
from __future__ import annotations

from pathlib import Path

from .client import UpdateError, Updater, platform_id
from .keys import TrustStore
from .sources import DirSource, HttpSource

DEFAULTS = {"url": "", "channel": "stable", "layout": "tree", "auto": "ask"}


class UpdateService:
    def __init__(self, home: Path, settings: dict, launcher_version: str, trust: TrustStore | None = None):
        cfg = {**DEFAULTS, **(settings.get("updates") or {})}
        self.cfg, self.home, self.version = cfg, Path(home), launcher_version
        self.trust = trust if trust is not None else TrustStore.load()
        self._updater: Updater | None = None

    def _make(self) -> Updater:
        if self._updater is None:
            url = self.cfg["url"].strip()
            if not url:
                raise UpdateError("Updates are not set up yet. Add the update address in Settings.")
            source = DirSource(Path(url)) if Path(url).is_dir() else HttpSource(url)
            self._updater = Updater(self.home / "updates", source, self.trust, channel=self.cfg["channel"],
                                    layout=self.cfg["layout"], launcher_version=self.version, platform=platform_id())
        return self._updater

    def check(self) -> dict:
        try:
            return {"ok": True, **self._make().check()}
        except (UpdateError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "channel": self.cfg["channel"]}

    def install(self, name: str, progress=None, health_check=None) -> dict:
        try:
            return self._make().update(name, progress=progress, health_check=health_check)
        except (UpdateError, ValueError) as exc:
            return {"ok": False, "component": name, "error": str(exc)}

    def rollback(self, name: str) -> dict:
        try:
            return self._make().rollback(name, reason="rolled back by the user", mark_failed=True)
        except (UpdateError, ValueError) as exc:
            return {"ok": False, "component": name, "error": str(exc)}

    def status(self) -> dict:
        try:
            return {"ok": True, **self._make().status()}
        except (UpdateError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
