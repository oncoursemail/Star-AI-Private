"""What the launcher's Bridge calls for the PX page. Qt-free; returns a JSON string, never raises.

Settings used: "px": {"forge": "", "tokenFile": "", "org": "metallic"}. With no forge configured the page still shows the
curated roadmap and says the tracker is not connected. The last good result is cached so the page opens instantly and
keeps working with the forge offline (the page then shows how old the data is).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .build import Forge, PxError, build, load_roadmap

CACHE_SECONDS = 600


class PxService:
    def __init__(self, home: Path, settings: dict):
        self.cfg = settings.get("px") or {}
        self.cache = Path(home) / "px" / "px.json"

    def _forge(self) -> Forge | None:
        url = (self.cfg.get("forge") or "").strip()
        if not url:
            return None
        token = ""
        if self.cfg.get("tokenFile"):
            try:
                token = Path(self.cfg["tokenFile"]).read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
        return Forge(url, token, self.cfg.get("org") or "metallic")

    def data(self, refresh: bool = False) -> str:
        try:
            if not refresh and self.cache.is_file() and time.time() - self.cache.stat().st_mtime < CACHE_SECONDS:
                return self.cache.read_text(encoding="utf-8")
            data = build(load_roadmap(), self._forge())
            if data["forge"]["state"] == "offline" and self.cache.is_file():
                old = json.loads(self.cache.read_text(encoding="utf-8"))
                if old.get("forge", {}).get("state") in ("online", "partial"):
                    old["forge"] = {"state": "stale", "detail": data["forge"]["detail"]}
                    return json.dumps(old)
            text = json.dumps(data)
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(text, encoding="utf-8")
            return text
        except (PxError, OSError, ValueError) as exc:
            return json.dumps({"error": str(exc)})
