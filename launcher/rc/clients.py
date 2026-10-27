"""The Rec Room clients on this PC: the owner's 2026 baseline and the partner revivals (Campus, NexaNet, Meow.Net).

Detection is RC's own `discover` (a short, fixed list of known folders; no disk-wide scan) merged with RC's catalog
(`list`) of what has been registered. Each client gets one honest state:

  not_found      nothing at the known location
  found          there, but not registered yet (registering only reads files)
  registered     registered; not checked in this session
  verified       registered and its launch files matched when last checked
  changed        registered and a launch file no longer matches its baseline
  needs_launcher modified client: it must be started through its own launcher, which is not registered yet

Partner names are plain text. No partner logos or marks are used (there is no permission for them).
"""
from __future__ import annotations

import ntpath

from .errors import ACTIONS

# key -> (prefix of the name RC prints, display name, one line about it)
KNOWN = {
    "steam": ("rec room", "Rec Room 2026 (Steam)", "Your installed Steam client. This is the baseline Metallic RC is built around."),
    "campus": ("campus", "Campus", "A community revival of Rec Room. Started through its own launcher."),
    "nexanet": ("nexanet", "NexaNet", "A community revival. Modified client: it needs its own launcher."),
    "meownet": ("meow", "MeowNet", "A community revival. Modified client: it needs its own launcher."),
}
PARTNER_KEYS = ("campus", "nexanet", "meownet")


def norm(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path or ""))


def key_for(name: str) -> str | None:
    low = (name or "").lower()
    for key, (prefix, _, _) in KNOWN.items():
        if low.startswith(prefix):
            return key
    return None


class Clients:
    """Builds the client list from RC's `discover` and `list`, plus the last verification results this session."""

    def __init__(self):
        self.verified: dict[str, dict] = {}  # installation id -> {"isValid", "at", "issues"}

    def record_verification(self, installation_id: str, valid: bool, at: float, errors: list[dict]) -> None:
        self.verified[installation_id] = {"isValid": valid, "at": at, "problems": errors[:20]}

    def build(self, discovered: list[dict], registered: list[dict]) -> list[dict]:
        by_root = {norm(i.get("installRoot", "")): i for i in registered}
        used: set[str] = set()
        entries: dict[str, dict] = {}
        for d in discovered:
            key = key_for(d.get("name", ""))
            if not key or key in entries:
                continue
            root = norm(d.get("installRoot", ""))
            reg = by_root.get(root)
            if reg:
                used.add(reg["id"])
            entries[key] = self._entry(key, d, reg)
        for key in KNOWN:  # keep every known client visible, even when it is not on this PC
            if key not in entries:
                entries[key] = self._entry(key, None, None)
        out = [entries[k] for k in KNOWN]
        for reg in registered:  # clients the owner added from other folders
            if reg["id"] not in used:
                out.append(self._entry("custom:" + reg["id"], None, reg, custom=True))
        return out

    def _entry(self, key: str, found: dict | None, reg: dict | None, *, custom: bool = False) -> dict:
        _, name, blurb = KNOWN.get(key, ("", reg["displayName"] if reg else key, "A client you added yourself."))
        inv = (reg or {}).get("inventory") or {}
        ext = (reg or {}).get("externalLauncher")
        modified = bool(inv.get("externalModificationsDetected"))
        launcher_hint = (found or {}).get("launcherPath")
        must_use_launcher = modified or key in ("nexanet", "meownet") or (key == "campus" and bool(ext or launcher_hint))
        ver = self.verified.get(reg["id"]) if reg else None
        if not found and not reg:
            state = "not_found"
        elif not reg:
            state = "found"
        elif modified and not ext:
            state = "needs_launcher"
        elif ver and not ver["isValid"]:
            state = "changed"
        elif ver:
            state = "verified"
        else:
            state = "registered"
        actions: list[str] = []
        if state == "found":
            actions = ["register_launcher" if must_use_launcher and not launcher_hint else "register_client"]
        elif state == "needs_launcher":
            actions = ["register_launcher"]
        elif state == "changed":
            actions = ["rebaseline"]
        elif state == "not_found":
            actions = ["install_from_steam" if key == "steam" else "locate_client"]
        return {
            "key": key, "name": name if not custom else (reg or {}).get("displayName", name), "blurb": blurb,
            "kind": "baseline" if key == "steam" else ("partner" if key in PARTNER_KEYS else "custom"),
            "state": state,
            "installRoot": (reg or found or {}).get("installRoot"),
            "installationId": reg["id"] if reg else None,
            "evidence": (found or {}).get("evidence"),
            "launcherPath": (ext or {}).get("executablePath") or launcher_hint,
            "launcherRegistered": bool(ext),
            "usesOwnLauncher": must_use_launcher,
            "unityVersion": inv.get("unityVersion"),
            "files": inv.get("fileCount"),
            "bytes": inv.get("totalBytes"),
            "verification": ver,
            "canLaunch": state in ("registered", "verified") or state == "found" and key == "steam",
            "actions": [{"id": a, "label": ACTIONS.get(a, a)} for a in actions],
        }

    @staticmethod
    def find(entries: list[dict], key: str) -> dict | None:
        return next((e for e in entries if e["key"] == key or e.get("installationId") == key), None)
