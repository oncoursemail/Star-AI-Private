#!/usr/bin/env python3
"""Offline research provenance checker. No network or repository writes.

Usage: python tools/research_audit.py manifest.json --root docs/research/recovered
Manifest JSON: {"items":[{"source":"chat-or-file","path":"relative/path.md","sha256":"64 hex digits","status":"MERGED"}]}
Exit nonzero on missing files, invalid paths, checksum mismatches or invalid status.
"""
import argparse
import hashlib
import json
from pathlib import Path

STATES = {"MERGED", "PR_ONLY", "LOCAL_ONLY", "PARTIAL", "UNKNOWN"}

def check(manifest: dict, root: Path) -> list[str]:
    errors = []
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
        return ["manifest must contain an items array"]
    root = root.resolve()
    seen = set()
    for i, item in enumerate(manifest["items"]):
        if not isinstance(item, dict):
            errors.append(f"item {i}: not an object")
            continue
        name = item.get("path")
        status = item.get("status")
        digest = item.get("sha256")
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            errors.append(f"item {i}: invalid relative path")
            continue
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path == root:
            errors.append(f"item {i}: path escapes root")
            continue
        if name in seen:
            errors.append(f"item {i}: duplicate path")
        seen.add(name)
        if status not in STATES:
            errors.append(f"item {i}: invalid status")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            errors.append(f"item {i}: invalid lowercase sha256")
            continue
        if status == "MERGED" and not item.get("commit"):
            errors.append(f"item {i}: MERGED requires commit evidence")
        if status == "PR_ONLY" and not item.get("pr"):
            errors.append(f"item {i}: PR_ONLY requires PR evidence")
        if not path.is_file():
            errors.append(f"item {i}: file missing: {name}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            errors.append(f"item {i}: sha256 mismatch: {name}")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path("docs/research/recovered"))
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    problems = check(data, args.root)
    for problem in problems:
        print("ERROR:", problem)
    if problems:
        return 1
    print(f"OK: verified {len(data['items'])} research artifact(s)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
