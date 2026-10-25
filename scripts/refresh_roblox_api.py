#!/usr/bin/env python3
"""Regenerate data/roblox_api/roblox_api.json from Roblox's official Studio API dump.

Source: Roblox publishes the Studio build that is live on its client settings service, and the matching
``<version>-Full-API-Dump.json`` on its setup CDN. This script asks for the live Windows Studio version, downloads
that build's Full API dump, validates it and writes a compact copy that keeps the Full API dump schema
(``Classes`` with ``Name``, ``Superclass``, ``Tags`` and ``Members``; ``Enums``; ``Version``), so the existing
``star.roblox_api_checker.load_api_dump`` reads it unchanged. Dropped fields: serialization, thread safety,
capabilities, defaults and member categories. Kept: member kinds, value, parameter and return types, string tags
(Deprecated, ReadOnly, Yields, ...), non-default security and ``PreferredDescriptorName`` replacements.

Usage:
    python scripts/refresh_roblox_api.py                 # download the live dump and rewrite the data file
    python scripts/refresh_roblox_api.py --input dump.json --version-upload version-abc --studio-version 0.1.2.3
    python scripts/refresh_roblox_api.py --check         # verify the committed file without writing anything

Standard library only. Network access goes only to the two official Roblox hosts below, over HTTPS, with a size
cap; nothing downloaded is executed. The output stays under MAX_OUTPUT_BYTES (the repository's 5 MB file limit).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "roblox_api" / "roblox_api.json"
VERSION_URL = "https://clientsettings.roblox.com/v2/client-version/WindowsStudio64"
DUMP_URL = "https://setup.rbxcdn.com/{upload}-Full-API-Dump.json"
ALLOWED_HOSTS = frozenset(("clientsettings.roblox.com", "setup.rbxcdn.com"))
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 5 * 1000 * 1000
TIMEOUT_SECONDS = 60
_UPLOAD = re.compile(r"version-[0-9a-f]{16}\Z")
_STUDIO_VERSION = re.compile(r"\d+\.\d+\.\d+\.\d+\Z")


def _fetch(url: str, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise ValueError(f"refusing to fetch {url!r}: only HTTPS from {sorted(ALLOWED_HOSTS)}")
    request = urllib.request.Request(url, headers={"User-Agent": "STAR-roblox-api-refresh"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - host allow-listed
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{url} is larger than {limit} bytes")
    return data


def live_studio_version() -> tuple[str, str]:
    """(studio version, clientVersionUpload) for the Studio build that is live now."""
    info = json.loads(_fetch(VERSION_URL, 64 * 1024))
    version, upload = info.get("version"), info.get("clientVersionUpload")
    if not isinstance(version, str) or not _STUDIO_VERSION.match(version):
        raise ValueError("client settings returned no Studio version")
    if not isinstance(upload, str) or not _UPLOAD.match(upload):
        raise ValueError("client settings returned no clientVersionUpload")
    return version, upload


def _type(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("Name"), str):
        raise ValueError("malformed type entry")
    result = {"Name": value["Name"]}
    if isinstance(value.get("Category"), str):
        result["Category"] = value["Category"]
    return result


def _tags(raw: object) -> tuple[list[str], str | None]:
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        raise ValueError("malformed tags")
    names = [t for t in raw if isinstance(t, str)]
    preferred = next((t["PreferredDescriptorName"] for t in raw
                      if isinstance(t, dict) and isinstance(t.get("PreferredDescriptorName"), str)), None)
    return names, preferred


def compact(dump: dict, *, minimum_classes: int = 100, minimum_enums: int = 50) -> dict:
    """Validate a Full API dump (or an earlier compact copy) and return the pruned copy: same schema, fewer fields."""
    if not isinstance(dump, dict) or dump.get("Version") != 1:
        raise ValueError("expected a Roblox Full API dump with Version 1")
    classes, enums = dump.get("Classes"), dump.get("Enums")
    if not isinstance(classes, list) or len(classes) < minimum_classes or not isinstance(enums, list)             or len(enums) < minimum_enums:
        raise ValueError("Full API dump is missing Classes or Enums")
    out_classes = []
    seen: set[str] = set()
    for entry in classes:
        if not isinstance(entry, dict) or not isinstance(entry.get("Name"), str) or entry["Name"] in seen:
            raise ValueError("malformed or duplicate class")
        if not isinstance(entry.get("Superclass"), str) or not isinstance(entry.get("Members"), list):
            raise ValueError(f"malformed class {entry['Name']}")
        seen.add(entry["Name"])
        tags, preferred = _tags(entry.get("Tags"))
        preferred = preferred or entry.get("PreferredDescriptorName")
        item: dict = {"Name": entry["Name"], "Superclass": entry["Superclass"], "Tags": tags, "Members": []}
        if preferred:
            item["PreferredDescriptorName"] = preferred
        for member in entry["Members"]:
            if not isinstance(member, dict) or not isinstance(member.get("Name"), str) or \
                    member.get("MemberType") not in ("Property", "Function", "Event", "Callback"):
                raise ValueError(f"malformed member in {entry['Name']}")
            m: dict = {"Name": member["Name"], "MemberType": member["MemberType"]}
            mtags, mpreferred = _tags(member.get("Tags"))
            mpreferred = mpreferred or member.get("PreferredDescriptorName")
            if mtags:
                m["Tags"] = mtags
            if mpreferred:
                m["PreferredDescriptorName"] = mpreferred
            if "ValueType" in member:
                m["ValueType"] = _type(member["ValueType"])
            if "Parameters" in member:
                params = []
                for p in member["Parameters"]:
                    if not isinstance(p, dict) or not isinstance(p.get("Name"), str):
                        raise ValueError(f"malformed parameter in {entry['Name']}.{member['Name']}")
                    q = {"Name": p["Name"], "Type": _type(p.get("Type"))}
                    if "Default" in p:
                        q["Default"] = p["Default"]
                    params.append(q)
                m["Parameters"] = params
            if "ReturnType" in member:
                ret = member["ReturnType"]
                m["ReturnType"] = [_type(r) for r in ret] if isinstance(ret, list) else _type(ret)
            security = member.get("Security")
            if security not in (None, "None", {"Read": "None", "Write": "None"}):
                m["Security"] = security
            item["Members"].append(m)
        out_classes.append(item)
    for entry in out_classes:
        if entry["Superclass"] not in seen and entry["Superclass"] not in ("<<<ROOT>>>", ""):
            raise ValueError(f"unknown superclass {entry['Superclass']} of {entry['Name']}")
    out_enums = []
    for enum in enums:
        if not isinstance(enum, dict) or not isinstance(enum.get("Name"), str) or not isinstance(enum.get("Items"), list):
            raise ValueError("malformed enum")
        items = []
        for it in enum["Items"]:
            if not isinstance(it, dict) or not isinstance(it.get("Name"), str) or not isinstance(it.get("Value"), int):
                raise ValueError(f"malformed enum item in {enum['Name']}")
            row: dict = {"Name": it["Name"], "Value": it["Value"]}
            itags, _ = _tags(it.get("Tags"))
            if itags:
                row["Tags"] = itags
            items.append(row)
        etags, _ = _tags(enum.get("Tags"))
        e: dict = {"Name": enum["Name"], "Items": items}
        if etags:
            e["Tags"] = etags
        out_enums.append(e)
    return {"Version": 1, "Classes": out_classes, "Enums": out_enums}


def render(data: dict, source: dict) -> str:
    """Deterministic JSON text with one member or enum per line, so refreshes diff cleanly."""
    dumps = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))  # noqa: E731
    lines = ['{"Classes":[']
    for ci, cls in enumerate(sorted(data["Classes"], key=lambda c: c["Name"])):
        head = {k: v for k, v in cls.items() if k != "Members"}
        lines.append('{"Members":[')
        members = sorted(cls["Members"], key=lambda m: (m["MemberType"], m["Name"]))
        for mi, member in enumerate(members):
            lines.append(dumps(member) + ("," if mi < len(members) - 1 else ""))
        tail = dumps(head)[1:]  # the remaining keys after "Members", in sorted order
        lines.append("]," + tail + ("," if ci < len(data["Classes"]) - 1 else ""))
    lines.append('],"Enums":[')
    enums = sorted(data["Enums"], key=lambda e: e["Name"])
    for ei, enum in enumerate(enums):
        lines.append(dumps(enum) + ("," if ei < len(enums) - 1 else ""))
    lines.append('],"StarSource":' + dumps(source) + ',"Version":1}')
    return "\n".join(lines) + "\n"


def build(raw: bytes, *, studio_version: str, upload: str, generated: str) -> str:
    dump = json.loads(raw.decode("utf-8"))
    source = {
        "clientVersionUpload": upload,
        "generated": generated,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "studioVersion": studio_version,
        "url": DUMP_URL.format(upload=upload),
    }
    text = render(compact(dump), source)
    json.loads(text)  # the writer must always produce valid JSON
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError(f"compact dataset exceeds {MAX_OUTPUT_BYTES} bytes")
    return text


def report_changes(old: dict, new: dict, changes_file: Path) -> str:
    """List what the new dump added or deprecated (star/api_dump_diff.py), store the lists beside the data file and
    queue them as curiosity items for night school. A failure here never stops the refresh."""
    try:
        sys.path.insert(0, str(ROOT))
        from star import api_dump_diff
        changes = api_dump_diff.diff_dumps(old, new)
        if not api_dump_diff.has_changes(changes):
            return "no API changes since the previous dump"
        api_dump_diff.write_changes(changes, changes_file)
        queued = api_dump_diff.queue_changes(changes)
        return (f"API changes: {len(changes['added_classes'])} classes, {len(changes['added_members'])} members added, "
                f"{len(changes['newly_deprecated'])} deprecated; {queued} queued for night school ({changes_file})")
    except Exception as exc:  # noqa: BLE001 - the refresh itself succeeded
        return f"API change list not written ({type(exc).__name__})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, help="a local Full-API-Dump.json instead of downloading")
    parser.add_argument("--version-upload", help="clientVersionUpload of --input, e.g. version-0123456789abcdef")
    parser.add_argument("--studio-version", help="Studio version of --input, e.g. 0.742.0.7421053")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true", help="validate the existing output file and exit")
    args = parser.parse_args(argv)

    if args.check:
        text = args.output.read_text(encoding="utf-8")
        data = json.loads(text)
        source = data.get("StarSource", {})
        if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
            print("dataset exceeds the size limit", file=sys.stderr)
            return 1
        rebuilt = render(compact(data), source)
        if rebuilt != text:
            print("dataset is not in canonical form; regenerate it with this script", file=sys.stderr)
            return 1
        print(f"ok: {len(data['Classes'])} classes, {len(data['Enums'])} enums, Studio {source.get('studioVersion')}")
        return 0

    if args.input:
        if not (args.version_upload and _UPLOAD.match(args.version_upload)):
            parser.error("--input needs --version-upload version-<16 hex digits>")
        if not (args.studio_version and _STUDIO_VERSION.match(args.studio_version)):
            parser.error("--input needs --studio-version like 0.742.0.7421053")
        raw = args.input.read_bytes()
        studio_version, upload = args.studio_version, args.version_upload
    else:
        studio_version, upload = live_studio_version()
        raw = _fetch(DUMP_URL.format(upload=upload))
    text = build(raw, studio_version=studio_version, upload=upload,
                 generated=_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d"))
    old_text = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    data = json.loads(text)
    if old_text:
        print(report_changes(json.loads(old_text), data, args.output.with_name("changes.json")))
    print(f"wrote {args.output} ({len(text.encode('utf-8'))} bytes): {len(data['Classes'])} classes, "
          f"{len(data['Enums'])} enums from Studio {studio_version} ({upload})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
