#!/usr/bin/env python3
"""Compare reviewed local compiler emission against its git baseline.

This runs only the compiler module from the selected existing Litha repository,
plus the same repository's git baseline. It does not fetch, install, execute
generated Luau, or load upstream third-party code. The 23 specifications below
are synthetic authoring examples, not real Roblox execution fixtures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types


COMPILER = "star/roblox_ui_compiler.py"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def compiler_module(raw: bytes, name: str, filename: str):
    module = types.ModuleType(name)
    module.__file__ = filename
    # dataclasses resolves the defining module by its name.
    sys.modules[name] = module
    exec(compile(raw, filename, "exec"), module.__dict__)
    return module


def specifications() -> list[tuple[str, dict]]:
    original_palette = {"white": "#FFFFFF", "black": "#111111", "muted": "#777777"}
    roots = {
        "shop": {"type": "screen", "id": "shop", "children": [
            {"type": "frame", "id": "panel", "background": "black", "corner": 12,
             "children": [{"type": "button", "id": "buy", "text": "Buy", "textColor": "white",
                           "background": "black", "states": {"hover": {"background": "muted"}}}]}]},
        "inventory": {"type": "screen", "id": "inventory", "children": [
            {"type": "grid", "id": "slots", "layout": {"kind": "grid", "columns": 4,
               "cellSize": {"x": {"offset": 60}, "y": {"offset": 60}}}, "children": [
               {"type": "image", "id": "sword", "image": "rbxassetid://1234"}]}]},
        "settings": {"type": "screen", "id": "settings", "children": [
            {"type": "frame", "id": "pane", "padding": 8,
             "stroke": {"color": "muted", "thickness": 1},
             "children": [{"type": "toggle", "id": "music", "text": "Music", "states": {
                 "selected": {"background": "muted", "duration": .2}}}]}]},
        "hud": {"type": "screen", "id": "hud", "children": [
            {"type": "progress", "id": "health", "value": .75, "aspectRatio": 6}]},
        "dialog": {"type": "screen", "id": "dialog", "children": [
            {"type": "input", "id": "reply", "placeholder": "Your reply", "textColor": "white",
             "background": "black", "states": {"pressed": {"transparency": .2}}}]},
        "leaderboard": {"type": "screen", "id": "leaderboard", "children": [
            {"type": "scroll", "id": "rows", "layout": {"kind": "list", "spacing": 4},
             "children": [{"type": "text", "id": "entry", "text": "Score"}]}]},
    }
    cases = [(name, {"palette": original_palette, "root": root}) for name, root in roots.items()]
    contrast_palette = {"black": "#000000", "white": "#FFFFFF", "boundary": "#00827F"}

    def control(**overrides):
        return {"type": "button", "id": "action", "text": "Continue",
                "background": "black", "textColor": "white", **overrides}

    def ui(child):
        return {"palette": contrast_palette, "root": {
            "type": "screen", "id": "screen", "children": [child]}}

    for kind in ("button", "toggle", "input"):
        for state in ("hover", "pressed", "selected", "disabled"):
            cases.append((f"state-{kind}-{state}", ui(control(
                type=kind, states={state: {"background": "white"}}))))
    for transparency in (0, .25, .5, .75, 1):
        cases.append((f"transparency-{transparency:g}", ui(control(transparency=transparency))))
    assert len(cases) == 23 and len({name for name, _ in cases}) == 23
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline-ref", default="a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)

    def git(*arguments: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(repo), *arguments])

    # Resolve an explicit commit before reading the file so moving refs cannot
    # change the selected baseline between the metadata and source reads.
    commit = git("rev-parse", "--verify", "--end-of-options", args.baseline_ref + "^{commit}").decode().strip()
    baseline_bytes = git("show", f"{commit}:{COMPILER}")
    candidate_bytes = (repo / COMPILER).read_bytes()
    baseline = compiler_module(baseline_bytes, "_parity_baseline", f"{commit}:{COMPILER}")
    candidate = compiler_module(candidate_bytes, "_parity_candidate", str(repo / COMPILER))
    records = []
    for ident, spec in specifications():
        # Separate JSON copies ensure neither implementation can alter the
        # other's input. Emission equality compares actual UTF-8 bytes.
        serialized = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
        before = baseline.compile_ui(json.loads(serialized)).source.encode("utf-8")
        after = candidate.compile_ui(json.loads(serialized)).source.encode("utf-8")
        records.append({"id": ident, "spec_sha256": sha256(serialized),
                        "baseline_source_sha256": sha256(before),
                        "candidate_source_sha256": sha256(after),
                        "baseline_source_bytes": len(before), "candidate_source_bytes": len(after),
                        "equal": before == after})

    identical = all(record["equal"] for record in records)
    # Detect a concurrent compiler edit while this verification was running.
    candidate_unchanged = (repo / COMPILER).read_bytes() == candidate_bytes
    result = {
        "schema_version": 1,
        "check": "roblox_ui_compiler_emission_parity",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "baseline": {"requested_ref": args.baseline_ref, "commit": commit,
                     "path": COMPILER, "file_sha256": sha256(baseline_bytes)},
        "candidate": {"path": COMPILER, "file_sha256": sha256(candidate_bytes),
                      "unchanged_during_check": candidate_unchanged},
        "verification_script_sha256": sha256(Path(__file__).read_bytes()),
        "case_count": len(records),
        "equal_count": sum(record["equal"] for record in records),
        "all_equal": identical,
        "cases": records,
        "limits": [
            "Synthetic specifications check deterministic emitted Luau bytes, not all possible compiler inputs.",
            "Generated Luau was not executed; Roblox runtime behavior and visual quality are unverified.",
            "Diagnostic warnings are intentionally allowed to differ between baseline and candidate.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "baseline_commit": commit,
                      "case_count": len(records), "equal_count": result["equal_count"],
                      "all_equal": identical, "candidate_unchanged": candidate_unchanged}))
    assert identical, "Generated source differs; inspect the saved case hashes."
    assert candidate_unchanged, "Compiler changed during verification; rerun against a stable candidate."
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
