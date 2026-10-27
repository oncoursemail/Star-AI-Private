"""Where RC things live. Everything is derived from two roots so tests and screenshots can redirect them:

  METALLIC_LAUNCHER_HOME  the launcher's own data (default %LOCALAPPDATA%\\Metallic\\Launcher); the RC module keeps its
                          managed tools, package cache, settings and log under <home>\\rc
  METALLIC_RC_HOME        Metallic-RC's own folder (default %LOCALAPPDATA%\\Metallic-RC): the client catalog written by
                          the RC tools (launcher\\), the owned backend (backend\\) and the older desktop build
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

TOOLS_EXE = "Metallic.RC.Launcher.exe"
BACKEND_TASK = "Metallic-RC-Backend"
BACKEND_PORT = 4187
STEAM_APP_ID = 471710  # Rec Room on Steam; used only for the "install from Steam" link


@dataclass(frozen=True)
class Paths:
    launcher_home: Path
    rc_home: Path

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Paths":
        env = os.environ if env is None else env
        local = Path(env.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        home = Path(env["METALLIC_LAUNCHER_HOME"]) if env.get("METALLIC_LAUNCHER_HOME") else local / "Metallic" / "Launcher"
        rc = Path(env["METALLIC_RC_HOME"]) if env.get("METALLIC_RC_HOME") else local / "Metallic-RC"
        return cls(home, rc)

    # -- the module's own files ---------------------------------------------------------------------------------
    @property
    def module_dir(self) -> Path:
        return self.launcher_home / "rc"

    @property
    def settings_file(self) -> Path:
        return self.module_dir / "settings.json"

    @property
    def log_file(self) -> Path:
        return self.module_dir / "rc.log"

    @property
    def tools_dir(self) -> Path:
        """Managed tools: versions\\<version>\\ and current.json."""
        return self.module_dir / "tools"

    @property
    def cache_dir(self) -> Path:
        return self.module_dir / "cache"

    # -- Metallic-RC's own files (read through RC's interfaces, never edited) -----------------------------------
    @property
    def state_dir(self) -> Path:
        return self.rc_home / "launcher"

    @property
    def backend_dir(self) -> Path:
        return self.rc_home / "backend"

    @property
    def legacy_tools_exe(self) -> Path:
        """The desktop build the RC agent installed on 2026-10-20. Adopted when there is no managed install."""
        return self.rc_home / "rework-20261020" / "desktop-win-x64" / TOOLS_EXE

    @property
    def legacy_packages_dir(self) -> Path:
        return self.rc_home / "rework-20261020" / "packages"
