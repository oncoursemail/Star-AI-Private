"""What the launcher's Bridge calls for the PX page. Qt-free; returns a JSON string, never raises.

Settings used: "px": {"forge": "", "tokenFile": "", "org": "metallic", "api": "", "apiFingerprint": ""}. With "api"
set (and no forge of its own) the data comes from Metallic API v1 GET /v1/progress (public view; no forge token on this
PC). With neither, the page still shows the curated roadmap and says the tracker is not connected. The last good result is cached so the page opens instantly and
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

    def _from_api(self) -> dict | None:
        """Metallic API v1 progress (public view), or None when not configured or unreachable."""
        url = (self.cfg.get("api") or "").strip()
        if not url or (self.cfg.get("forge") or "").strip():
            return None
        from ..metallic_api import MetallicAPI, MetallicAPIError
        try:
            return MetallicAPI(url, fingerprint=self.cfg.get("apiFingerprint") or None, timeout=15,
                               user_agent="metallic-launcher-px").get_progress()
        except MetallicAPIError:
            return None

    def data(self, refresh: bool = False) -> str:
        try:
            if not refresh and self.cache.is_file() and time.time() - self.cache.stat().st_mtime < CACHE_SECONDS:
                return self.cache.read_text(encoding="utf-8")
            data = self._from_api() or build(load_roadmap(), self._forge())
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
