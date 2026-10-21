"""Load a Rojo-style game folder and build one self-contained Luau bundle for the twin driver.

Game folder layout (as in ``examples/roblox/twin_tycoon``)::

    twin.json                      {"name": ..., "adapter": "twin.luau", "base": "../other"?}
    twin.luau                      client-side adapter (what a player sees and can do)
    ServerScriptService/X.server.luau   -> Script (runs at start)
    ServerScriptService/Y.luau          -> ModuleScript
    ReplicatedStorage/Shared/Z.luau     -> ModuleScript in Folder "Shared"

``base`` layers the folder on another one: files with the same relative path replace the base's.
``*.client.luau`` files and ``Tests``/``*.spec.luau`` are not run (logic twins are server-side).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

LUAU_DIR = Path(__file__).with_name("luau")
SERVICES = ("ServerScriptService", "ReplicatedStorage", "ServerStorage", "Workspace")
# Order must match W.envFor in engine.luau; the last three are shadowed with nil on purpose.
ENV_PARAMS = ("script, game, workspace, require, task, Instance, Enum, Vector3, Vector2, CFrame, Color3, "
              "UDim2, Random, typeof, tick, time, wait, delay, spawn, os, warn, print, _G, shared, "
              "getfenv, setfenv, loadstring")
_EXPORT_TYPE = re.compile(r"(?m)^(\s*)export\s+type\b")


@dataclass
class GameFile:
    rel: str
    path: list[str]
    kind: str  # "Script" | "ModuleScript"
    source: str


@dataclass
class Game:
    name: str
    root: Path
    files: list[GameFile]
    adapter: str
    adapter_path: str
    skipped: list[str] = field(default_factory=list)


def _manifest(root: Path) -> dict:
    path = root / "twin.json"
    if not path.is_file():
        raise FileNotFoundError(f"{root} has no twin.json (see star/player_twins/bundle.py)")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object")
    return data


def _collect(root: Path, chain: list[Path]) -> tuple[dict[str, Path], dict]:
    if root in chain:
        raise ValueError(f"twin.json base loop at {root}")
    manifest = _manifest(root)
    files: dict[str, Path] = {}
    if manifest.get("base"):
        base_files, base_manifest = _collect((root / manifest["base"]).resolve(), chain + [root])
        files.update(base_files)
        manifest = {**base_manifest, **manifest}
    for service in SERVICES:
        for f in sorted((root / service).rglob("*.luau")) if (root / service).is_dir() else []:
            files[f.relative_to(root).as_posix()] = f
    adapter = root / manifest.get("adapter", "twin.luau")
    if adapter.is_file():
        files["@adapter"] = adapter
    return files, manifest


def load_game(game_dir: str | Path) -> Game:
    root = Path(game_dir).resolve()
    found, manifest = _collect(root, [])
    adapter_path = found.pop("@adapter", None)
    if adapter_path is None:
        raise FileNotFoundError(f"no adapter ({manifest.get('adapter', 'twin.luau')}) for {root}")
    files: list[GameFile] = []
    skipped: list[str] = []
    for rel, path in sorted(found.items()):
        parts = rel.split("/")
        name = parts[-1]
        if name.endswith(".client.luau") or name.endswith(".spec.luau") or "Tests" in parts[:-1]:
            skipped.append(rel)
            continue
        if name.endswith(".server.luau"):
            kind, stem = "Script", name[: -len(".server.luau")]
        else:
            kind, stem = "ModuleScript", name[: -len(".luau")]
        inst_path = parts[:-1] if stem == "init" else parts[:-1] + [stem]
        files.append(GameFile(rel, inst_path, kind, path.read_text(encoding="utf-8")))
    return Game(str(manifest.get("name", root.name)), root, files,
                adapter_path.read_text(encoding="utf-8"), str(adapter_path), skipped)


def to_luau(value) -> str:
    """Python data -> Luau table literal."""
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite number in config")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "{" + ", ".join(to_luau(v) for v in value) + "}"
    if isinstance(value, dict):
        items = []
        for k, v in value.items():
            key = k if re.fullmatch(r"[A-Za-z_]\w*", str(k)) else f"[{json.dumps(str(k))}]"
            items.append(f"{key} = {to_luau(v)}")
        return "{" + ", ".join(items) + "}"
    raise TypeError(f"cannot convert {type(value).__name__} to Luau")


class Bundle:
    """Concatenated Luau source plus a map from bundle lines back to original files."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.spans: list[tuple[int, int, str]] = []  # (first bundle line, count, label)

    def add(self, text: str, label: str | None = None) -> None:
        chunk = text.splitlines()
        if label:
            self.spans.append((len(self.lines) + 1, len(chunk), label))
        self.lines.extend(chunk)

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + "\n"

    def locate(self, line: int) -> str:
        for first, count, label in self.spans:
            if first <= line < first + count:
                return f"{label}:{line - first + 1}"
        return f"bundle:{line}"


_BUNDLE_REF = re.compile(r'(?:\[string ")?(?:[^\s"\[]*[\\/])?twins_bundle_\d+(?:\.luau)?(?:"\])?:(\d+)(?=:)')


def map_lines(text: str, bundle: Bundle) -> str:
    return _BUNDLE_REF.sub(lambda m: bundle.locate(int(m.group(1))), text)


def build(game: Game, config: dict) -> Bundle:
    b = Bundle()
    b.add("-- generated by star.player_twins; do not edit")
    b.add("local __CONFIG = " + to_luau(config))
    b.add("local __FILES = {}")
    for f in game.files:
        b.add(f"table.insert(__FILES, {{ path = {to_luau(f.path)}, kind = {json.dumps(f.kind)}, "
              f"factory = function({ENV_PARAMS})")
        b.add(_EXPORT_TYPE.sub(r"\1type", f.source), label=f.rel)
        b.add("end })")
    b.add("local __ADAPTER = (function()")
    b.add(game.adapter, label=Path(game.adapter_path).name)
    b.add("end)()")
    for module in ("engine", "json", "human", "fuzz"):
        name = {"engine": "Engine", "json": "Json", "human": "Human", "fuzz": "Fuzz"}[module]
        b.add(f"local {name} = (function()")
        b.add((LUAU_DIR / f"{module}.luau").read_text(encoding="utf-8"), label=f"player_twins/luau/{module}.luau")
        b.add("end)()")
    b.add((LUAU_DIR / "driver.luau").read_text(encoding="utf-8"), label="player_twins/luau/driver.luau")
    return b
