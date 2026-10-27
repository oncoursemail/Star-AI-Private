"""Which machine is this? Computer use runs only on STAR's own PC, never on the owner's (owner rule, 2026-10-26).

The owner enrolls her PC once, on that PC: `python -m star.computer enroll --star-pc`. That writes
<home>\\machine.json with the role "star-pc" and a fingerprint: SHA-256 of this Windows installation's MachineGuid
(HKLM\\SOFTWARE\\Microsoft\\Cryptography), never the GUID itself. Every driver start compares the fingerprint with the
machine it runs on. No profile, another role, or another fingerprint (the folder copied to the owner's PC, STAR_HOME_DIR
pointed at a copy) = `WrongMachine`: nothing is observed or touched. STAR's own actions cannot write the home folder
(star/home/host.py), so she cannot enroll a machine herself.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Callable

PROFILE_NAME = "machine.json"
ROLE = "star-pc"


class WrongMachine(RuntimeError):
    """This is not STAR's enrolled PC: computer use refuses to start."""


def machine_guid() -> str:  # pragma: no cover - reads the Windows registry
    import winreg
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                         winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    try:
        return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    finally:
        winreg.CloseKey(key)


def fingerprint(read_guid: Callable[[], str] = machine_guid) -> str:
    guid = str(read_guid() or "").strip().lower()
    if not guid:
        raise WrongMachine("this machine has no MachineGuid to identify it")
    return hashlib.sha256(("star-pc:" + guid).encode("utf-8")).hexdigest()


def profile_path(home: Path) -> Path:
    return Path(home) / PROFILE_NAME


def enroll(home: Path, read_guid: Callable[[], str] = machine_guid) -> Path:
    """Owner only, on her PC: mark this machine as STAR's own."""
    path = profile_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"role": ROLE, "fingerprint": fingerprint(read_guid),
                                "enrolled": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1),
                    encoding="utf-8")
    return path


def check(home: Path, read_guid: Callable[[], str] = machine_guid) -> tuple[bool, str]:
    """(True, "") on STAR's enrolled PC, else (False, why)."""
    try:
        saved = json.loads(profile_path(home).read_text(encoding="utf-8-sig"))
    except OSError:
        return False, "this PC is not enrolled as STAR's PC (owner: python -m star.computer enroll --star-pc on her PC)"
    except ValueError:
        return False, "machine.json is not valid JSON"
    if not isinstance(saved, dict) or saved.get("role") != ROLE:
        return False, f"machine.json role is {saved.get('role') if isinstance(saved, dict) else None!r}, not {ROLE!r}"
    try:
        here = fingerprint(read_guid)
    except Exception as why:
        return False, f"cannot identify this machine ({type(why).__name__})"
    if str(saved.get("fingerprint") or "") != here:
        return False, "this is not the machine that was enrolled as STAR's PC"
    return True, ""


def require(home: Path, read_guid: Callable[[], str] = machine_guid) -> None:
    ok, why = check(home, read_guid)
    if not ok:
        raise WrongMachine(why)
