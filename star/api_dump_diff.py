"""What changed between two Roblox API dumps (issue #555 A3): added and deprecated members, queued as curiosity items.

`diff_dumps(old, new)` compares two copies of data/roblox_api/roblox_api.json (the Full API dump schema) and
`diff_deprecated(old_rows, new_rows)` two copies of data/roblox_api/deprecated.json's `members`. `write_changes`
stores the lists in data/roblox_api/changes.json (what the next refresh run or the weekly self-audit reads) and
`queue_changes` adds one curiosity item per new class, per class that gained members, and per newly deprecated
member (star/curiosity.py), so night school writes practice tasks for them. Both refresh scripts call these before
they overwrite the old file: `python scripts/refresh_roblox_api.py` and `python -m star.roblox_deprecated refresh`.

    python -m star.api_dump_diff OLD.json NEW.json [--write] [--queue]
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from . import curiosity

CHANGES_FILE = Path(__file__).resolve().parents[1] / "data" / "roblox_api" / "changes.json"
LIST_LIMIT = 200            # entries kept per list in changes.json
MAX_QUEUED = 60             # curiosity items one refresh may add
MEMBERS_PER_ITEM = 6


def _source(dump: dict) -> dict:
    source = dump.get("StarSource")
    if not isinstance(source, dict):
        source = {}
    return {k: source.get(k) for k in ("studioVersion", "clientVersionUpload", "generated") if source.get(k)}


def _members(dump: dict) -> tuple[dict, dict]:
    """({class: superclass}, {(class, member, kind): (tags, preferred)}) of a dump."""
    classes, members = {}, {}
    for cls in dump.get("Classes") or []:
        classes[cls["Name"]] = cls.get("Superclass", "")
        for member in cls.get("Members") or []:
            members[(cls["Name"], member["Name"], member.get("MemberType", ""))] = (
                frozenset(member.get("Tags") or ()), member.get("PreferredDescriptorName") or "")
    return classes, members


def _enum_items(dump: dict) -> dict[str, set]:
    return {e["Name"]: {i["Name"] for i in e.get("Items") or []} for e in dump.get("Enums") or []}


def diff_dumps(old: dict, new: dict) -> dict:
    old_classes, old_members = _members(old)
    new_classes, new_members = _members(new)
    old_enums, new_enums = _enum_items(old), _enum_items(new)
    added_classes = sorted(set(new_classes) - set(old_classes))
    fresh = set(added_classes)
    added = sorted(f"{c}.{m} ({k})" for (c, m, k) in set(new_members) - set(old_members) if c not in fresh)
    removed = sorted(f"{c}.{m} ({k})" for (c, m, k) in set(old_members) - set(new_members) if c in new_classes)
    def label(c, m, k):
        return f"{c}.{m}" + (f" -> {new_members[(c, m, k)][1]}" if new_members[(c, m, k)][1] else "")
    deprecated = sorted(label(*key) for key in new_members
                        if "Deprecated" in new_members[key][0] and key[0] not in fresh
                        and ("Deprecated" not in old_members.get(key, ((), ""))[0]))
    return {"old": _source(old), "new": _source(new),
            "added_classes": [f"{c} ({new_classes[c] or 'root'})" for c in added_classes],
            "removed_classes": sorted(set(old_classes) - set(new_classes)),
            "added_members": added, "removed_members": removed, "newly_deprecated": deprecated,
            "added_enums": sorted(set(new_enums) - set(old_enums)),
            "added_enum_items": sorted(f"Enum.{n}.{i}" for n in set(new_enums) & set(old_enums)
                                       for i in new_enums[n] - old_enums[n])}


def diff_deprecated(old_rows: list, new_rows: list) -> list[str]:
    """Members the docs' deprecated inventory lists now but did not before ("Class.Member -> replacement")."""
    def key(row):
        return (row.get("owner"), row.get("member"))
    seen = {key(r) for r in old_rows}
    return sorted(f"{r['owner']}.{r['member']}" + (f" -> {r['replacement']}" if r.get("replacement") else "")
                  for r in new_rows if key(r) not in seen)


def has_changes(changes: dict) -> bool:
    return any(changes.get(k) for k in ("added_classes", "removed_classes", "added_members", "removed_members",
                                        "newly_deprecated", "added_enums", "added_enum_items"))


def write_changes(changes: dict, path: Path = CHANGES_FILE, *, today: str = "") -> Path:
    """Store the lists (each capped at LIST_LIMIT, with the full count) in the data folder."""
    out = {"generated": today or curiosity._now()[:10], "old": changes.get("old", {}), "new": changes.get("new", {})}
    for name in ("added_classes", "removed_classes", "added_members", "removed_members", "newly_deprecated",
                 "added_enums", "added_enum_items"):
        rows = changes.get(name, [])
        out[name] = rows[:LIST_LIMIT]
        out[name + "_total"] = len(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def queue_changes(changes: dict, *, path: Path | None = None) -> int:
    """One curiosity item per new class, per class with new members and per newly deprecated member."""
    queued = 0
    version = (changes.get("new") or {}).get("studioVersion", "")
    note = f"Studio {version}" if version else "latest Studio dump"
    items: list[tuple[str, str]] = []
    for entry in changes.get("newly_deprecated", []):
        items.append((f"Roblox API deprecated: {entry}", note))
    for entry in changes.get("added_classes", []):
        items.append((f"new Roblox class {entry}", note))
    by_class: dict[str, list[str]] = {}
    for entry in changes.get("added_members", []):
        owner, _, rest = entry.partition(".")
        by_class.setdefault(owner, []).append(rest.split(" ")[0])
    for owner, names in sorted(by_class.items()):
        extra = f" (+{len(names) - MEMBERS_PER_ITEM} more)" if len(names) > MEMBERS_PER_ITEM else ""
        items.append((f"new Roblox API members on {owner}: {', '.join(names[:MEMBERS_PER_ITEM])}{extra}", note))
    for topic, detail in items[:MAX_QUEUED]:
        queued += curiosity.record("api_change", topic, detail, path=path)
    return queued


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    flags = [a for a in args if a.startswith("--")]
    files = [a for a in args if not a.startswith("--")]
    if len(files) != 2:
        print("usage: python -m star.api_dump_diff OLD.json NEW.json [--write] [--queue]", file=sys.stderr)
        return 2
    changes = diff_dumps(*(json.loads(Path(f).read_text(encoding="utf-8")) for f in files))
    print(json.dumps({k: (v[:10] if isinstance(v, list) else v) for k, v in changes.items()}, indent=1))
    if "--write" in flags:
        print("wrote", write_changes(changes))
    if "--queue" in flags:
        print("queued", queue_changes(changes), "curiosity items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
