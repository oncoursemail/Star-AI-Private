"""The Minecraft index built by mesh.mcdata.build: one file per game version (command tree, registries, blocks, vanilla
data-driven ids, client asset names, sound events, pack formats). Identical subtrees are shared in memory.

    idx = McIndex.load("/var/lib/star-verify/mc")      # None-safe: McIndex.load(missing dir) -> empty index
    v = idx.get("1.21.11"); v.has("minecraft:item", "diamond")
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

VERSION_RE = re.compile(r"\b(1\.21(?:\.\d{1,2})?|2[6-9]\.\d(?:\.\d)?)\b")


def vkey(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def _intern(node, memo: dict):
    if isinstance(node, dict):
        node = {k: _intern(v, memo) for k, v in node.items()}
    elif isinstance(node, list):
        node = [_intern(v, memo) for v in node]
    else:
        return node
    key = json.dumps(node, sort_keys=True, separators=(",", ":")) if len(memo) < 600000 else None
    if key is None:
        return node
    return memo.setdefault(key, node)


def short(rid: str) -> str:
    return rid[10:] if rid.startswith("minecraft:") else rid


class McVersion:
    def __init__(self, data: dict, memo: dict):
        self.version = data["version"]
        self.pack = data.get("pack") or {}
        self.tree = _intern(data["commands"], memo)
        fs = memo.setdefault("__frozensets__", {})       # identical id sets are shared between versions

        def share(items) -> frozenset:
            f = frozenset(items)
            return fs.setdefault(f, f)
        self.registries = {short(k): share(short(e) for e in v) for k, v in data["registries"].items()}
        self.blocks = _intern({short(k): v for k, v in data["blocks"].items()}, memo)
        self.data = {k: share(v) for k, v in (data.get("data") or {}).items()}
        self.datapack = data.get("datapack") or {}
        self.assets = {k: share(v) for k, v in (data.get("assets") or {}).items()}
        self.sound_events = share(data.get("sound_events") or ())
        self.sound_files = share(data.get("sound_files") or ())
        self.lang = share(data.get("lang") or ())
        self.component_keys = data.get("component_keys") or {}
        self._ids = None

    @property
    def key(self) -> tuple:
        return vkey(self.version)

    def entries(self, registry: str) -> frozenset:
        """Ids of a registry: built-in (registries.json) or data-driven (vanilla files in data/minecraft/<registry>)."""
        registry = short(registry)
        if registry in self.registries:
            return self.registries[registry]
        return self.data.get(registry, frozenset())

    def has(self, registry: str, rid: str) -> bool | None:
        """True/False for a minecraft: id, None when the namespace is not minecraft (a pack's own id) or unknown."""
        rid = short(rid)
        if ":" in rid:
            return None
        ents = self.entries(registry)
        return (rid in ents) if ents else None

    def tags(self, registry: str) -> frozenset:
        return self.data.get("tags/" + short(registry), frozenset())

    def all_ids(self) -> frozenset:
        """Every minecraft: id this version knows (registries, vanilla data files, asset names, sound events)."""
        if self._ids is None:
            s = set()
            for v in self.registries.values():
                s |= v
            for v in self.data.values():
                s |= v
            for kind, v in self.assets.items():
                if kind in ("models", "textures", "items", "equipment", "font", "atlases", "blockstates", "shaders",
                            "post_effect", "particles", "waypoint_style"):
                    s |= v
            s |= self.sound_events
            s |= self.sound_files
            self._ids = frozenset(s)
        return self._ids

    def datapack_folders(self) -> set[str]:
        """Folder names a data pack may use under data/<ns>/ in this version."""
        dp = self.datapack.get("registries") or {}
        out = {short(k) for k, v in dp.items() if v.get("elements")}
        out |= {"tags/" + short(k) for k, v in dp.items() if v.get("tags")}
        out |= set((self.datapack.get("others") or {}).keys())
        out |= {"tags/function"} if "function" in out else set()
        if not dp:                                       # 1.21-1.21.3 have no datapack report: use vanilla folders
            out |= set(self.data.keys()) | {"function", "tags/function"}
            out |= {k.rsplit("/", 1)[0] if k.startswith("tags/") and k.count("/") > 1 and
                    k.split("/")[1] == "worldgen" else k for k in self.data}
        return out


class McIndex:
    def __init__(self, versions: dict[str, McVersion], meta: dict | None = None):
        self.versions = dict(sorted(versions.items(), key=lambda kv: vkey(kv[0])))
        self.meta = meta or {}

    @classmethod
    def load(cls, path: str | Path | None, only: list[str] | None = None) -> "McIndex":
        p = Path(path) if path else None
        if not p or not p.is_dir():
            return cls({})
        memo: dict = {}
        vers = {}
        for f in sorted(p.glob("mc-*.json.gz")):
            name = f.name[3:-8]
            if name.startswith("examples-"):
                continue
            if only and name not in only:
                continue
            vers[name] = McVersion(json.loads(gzip.decompress(f.read_bytes())), memo)
        meta = json.loads((p / "versions.json").read_text()) if (p / "versions.json").exists() else {}
        return cls(vers, meta)

    def __bool__(self) -> bool:
        return bool(self.versions)

    def get(self, version: str) -> McVersion | None:
        return self.versions.get(version)

    def java121(self) -> list[McVersion]:
        """The 1.21.x versions, newest first."""
        return [v for k, v in reversed(self.versions.items()) if k == "1.21" or k.startswith("1.21.")]

    def newest(self) -> McVersion | None:
        return next(reversed(self.versions.values()), None) if self.versions else None

    def resolve(self, text: str = "") -> list[McVersion]:
        """Versions to check against, preferred first: the version(s) the text names (1.21.4, 26.3; '1.21' = every
        1.21.x), else every 1.21.x newest first, then the newer releases."""
        named = []
        for m in VERSION_RE.finditer(text or ""):
            v = m.group(1)
            if v == "1.21":
                named += [x.version for x in self.java121()]
            elif v in self.versions:
                named.append(v)
        order = list(dict.fromkeys(named)) or [x.version for x in self.java121()]
        rest = [k for k in reversed(self.versions) if k not in order]
        return [self.versions[k] for k in order + rest]
