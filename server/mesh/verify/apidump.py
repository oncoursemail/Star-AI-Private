"""Roblox API index built from the public Full-API-Dump.json (MaximumADHD/Roblox-Client-Tracker, branch `roblox`).

`build_index(dump, version, fetched)` turns the ~8 MB dump into a compact index (classes with superclass, tags and
members; enums with items). `ApiIndex` answers lookups along the superclass chain and gives closest-name suggestions
that only ever come from names in the dump.

    python -m mesh.verify.apidump Full-API-Dump.json version.txt out.json     (build the index)
"""
from __future__ import annotations

import difflib
import json
import sys
import time
from pathlib import Path

DUMP_URL = "https://raw.githubusercontent.com/MaximumADHD/Roblox-Client-Tracker/roblox/Full-API-Dump.json"
VERSION_URL = "https://raw.githubusercontent.com/MaximumADHD/Roblox-Client-Tracker/roblox/version.txt"

# Security levels a normal game Script/LocalScript cannot use (PluginSecurity works in plugins only).
LOCKED = {"LocalUserSecurity", "RobloxScriptSecurity", "RobloxSecurity", "NotAccessibleSecurity"}
KINDS = {"Property": "p", "Function": "f", "Event": "e", "Callback": "c"}


def _pref(tags) -> str | None:
    for t in tags or []:
        if isinstance(t, dict) and t.get("PreferredDescriptorName"):
            return t["PreferredDescriptorName"]
    return None


def _security(member) -> str:
    sec = member.get("Security")
    if isinstance(sec, dict):
        levels = {sec.get("Read", "None"), sec.get("Write", "None")}
        read = sec.get("Read", "None")
        if read in LOCKED:
            return "locked"
        if read == "PluginSecurity":
            return "plugin"
        return "write-locked" if levels & LOCKED else ""
    if sec in LOCKED:
        return "locked"
    return "plugin" if sec == "PluginSecurity" else ""


def build_index(dump: dict, version: str = "", fetched: str = "") -> dict:
    classes = {}
    for c in dump.get("Classes", []):
        tags = [t for t in c.get("Tags") or [] if isinstance(t, str)]
        members = {}
        for m in c.get("Members", []):
            mtags = [t for t in m.get("Tags") or [] if isinstance(t, str)]
            vt = m.get("ValueType") or m.get("ReturnType") or {}
            if isinstance(vt, list):        # several return values: the first one is what a chain continues on
                vt = vt[0] if vt else {}
            entry = {"k": KINDS.get(m.get("MemberType"), "?")}
            if vt.get("Category") == "Class":
                entry["t"] = vt.get("Name")
            if "Deprecated" in mtags:
                entry["dep"] = 1
                pref = _pref(m.get("Tags"))
                if pref:
                    entry["pref"] = pref
            sec = _security(m)
            if sec:
                entry["sec"] = sec
            if "NotScriptable" in mtags:
                entry["ns"] = 1
            if m.get("MemberType") == "Event":
                params = [p.get("Type", {}) for p in m.get("Parameters") or []]
                entry["args"] = [p.get("Name") if p.get("Category") == "Class" else None for p in params]
            members[m["Name"]] = entry
        info = {"super": c.get("Superclass"), "members": members}
        for t in ("Service", "NotCreatable", "Deprecated", "NotBrowsable"):
            if t in tags:
                info.setdefault("tags", []).append(t)
        pref = _pref(c.get("Tags"))
        if pref:
            info["pref"] = pref
        classes[c["Name"]] = info
    enums = {}
    for e in dump.get("Enums", []):
        items, dep, legacy = [], {}, {}
        for it in e.get("Items", []):
            items.append(it["Name"])
            if "Deprecated" in [t for t in it.get("Tags") or [] if isinstance(t, str)]:
                dep[it["Name"]] = _pref(it.get("Tags")) or ""
            for old in it.get("LegacyNames") or []:
                legacy[old] = it["Name"]
        enums[e["Name"]] = {"items": items, "dep": dep, "legacy": legacy,
                            "deprecated": int("Deprecated" in (e.get("Tags") or []))}
    return {"meta": {"source": DUMP_URL, "version": version.strip(), "fetched": fetched or
                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "classes": len(classes), "enums": len(enums)},
            "classes": classes, "enums": enums}


def closest(name: str, candidates, n: int = 3, cutoff: float = 0.72) -> list[str]:
    """Closest names from `candidates` (case-insensitive exact match first). Never returns a name not in candidates."""
    cands = list(candidates)
    low = {c.lower(): c for c in cands}
    out = [low[name.lower()]] if name.lower() in low and low[name.lower()] != name else []
    by_low = difflib.get_close_matches(name.lower(), list(low), n=n + 1, cutoff=cutoff)
    for m in by_low:
        if low[m] not in out and low[m] != name:
            out.append(low[m])
    return out[:n]


class ApiIndex:
    def __init__(self, index: dict):
        self.meta = index.get("meta", {})
        self.classes: dict = index.get("classes", {})
        self.enums: dict = index.get("enums", {})
        self.services = [c for c, i in self.classes.items() if "Service" in i.get("tags", [])]
        self._all_members: set[str] | None = None
        self._chain_cache: dict[str, list[str]] = {}

    @classmethod
    def load(cls, path) -> "ApiIndex":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def chain(self, cls_name: str) -> list[str]:
        if cls_name not in self._chain_cache:
            out, c = [], cls_name
            while c and c in self.classes and c not in out:
                out.append(c)
                c = self.classes[c].get("super")
            self._chain_cache[cls_name] = out
        return self._chain_cache[cls_name]

    def member(self, cls_name: str, name: str) -> tuple[str, dict] | None:
        for c in self.chain(cls_name):
            m = self.classes[c]["members"].get(name)
            if m is not None:
                return c, m
        return None

    def members(self, cls_name: str, kind: str | None = None, include_deprecated: bool = False) -> list[str]:
        out = []
        for c in self.chain(cls_name):
            for n, m in self.classes[c]["members"].items():
                if (kind is None or m["k"] == kind) and (include_deprecated or not m.get("dep")) \
                        and not m.get("ns") and m.get("sec") != "locked" and n not in out:
                    out.append(n)
        return out

    def all_member_names(self) -> set[str]:
        if self._all_members is None:
            self._all_members = {n for i in self.classes.values() for n in i["members"]}
        return self._all_members

    def is_a(self, cls_name: str, base: str) -> bool:
        return base in self.chain(cls_name)

    def replacement(self, cls_name: str, name: str, member: dict) -> str | None:
        """The dump's preferred replacement for a deprecated member, else the PascalCase twin (connect -> Connect)."""
        pref = member.get("pref")
        if pref:
            return pref
        twin = name[:1].upper() + name[1:]
        if twin != name:
            found = self.member(cls_name, twin)
            if found and not found[1].get("dep"):
                return twin
        return None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    dump = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    version = Path(argv[1]).read_text(encoding="utf-8").strip() if Path(argv[1]).is_file() else argv[1]
    index = build_index(dump, version)
    Path(argv[2]).write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(index["meta"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
