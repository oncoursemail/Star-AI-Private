"""A stand-in for Metallic.RC.Launcher.exe used by the tests. It speaks the same JSON and exit codes as the real CLI
(checked against real output on 2026-10-26: discover, list, plan, verify, error objects) but touches nothing real.

Scenario files in the fake PC folder (FAKE_RC_PC):
  pc.json        {"clients": {"<root>": {"name","launcherPath","modified"}}}   what `discover` can see
  tamper.json    ["<installation id>"]                                        verify reports file_changed for these
  procs.json     {"pid": "image.exe"}                                         written by `launch`, read by the fake process list
  launch.fail    if present, `launch` prints process_start_failed
  launch.nopid   if present, `launch` succeeds but starts nothing
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def out(obj, code=0):
    print(json.dumps(obj, indent=1))
    sys.exit(code)


def err(code, message):
    print(json.dumps({"error": code, "message": message}), file=sys.stderr)
    sys.exit(1)


def take(args, name):
    if name in args:
        i = args.index(name)
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return None


def flag(args, name):
    if name in args:
        args.remove(name)
        return True
    return False


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main(argv):
    args = list(argv)
    pc = Path(os.environ["FAKE_RC_PC"])
    state = take(args, "--state-dir")
    cmd = args.pop(0) if args else "ui"
    catalog_path = Path(state) / "installations.json" if state else None
    cat = load(catalog_path, {"installations": []}) if catalog_path else {"installations": []}
    clients = load(pc / "pc.json", {"clients": {}})["clients"]

    if cmd == "discover":
        out([{"name": c["name"], "installRoot": root, "launcherPath": c.get("launcherPath"), "evidence": c.get("evidence", "Known location")}
             for root, c in clients.items()])
    if cmd == "list":
        out(cat["installations"])
    if cmd == "inspect":
        root = args[0]
        c = clients.get(root)
        ok = c is not None
        out({"rootPath": root, "canImport": ok, "issues": [] if ok else [{"severity": "error", "code": "directory_missing", "message": "The installation directory does not exist or is inaccessible."}]}, 0 if ok else 2)
    if cmd == "import":
        name = take(args, "--name")
        launcher = take(args, "--launcher")
        replace = flag(args, "--replace")
        root = args[0]
        c = clients.get(root)
        if c is None:
            err("inspection_failed", "The installation cannot be imported: directory_missing")
        iid = hashlib.md5(root.lower().encode()).hexdigest()
        existing = [i for i in cat["installations"] if i["id"] == iid]
        if existing and not replace:
            err("duplicate_installation", "This installation is already imported. Explicit replacement is required to accept a new fingerprint baseline.")
        cat["installations"] = [i for i in cat["installations"] if i["id"] != iid]
        inst = {"id": iid, "displayName": name, "installRoot": root,
                "inventory": {"externalModificationsDetected": bool(c.get("modified")), "unityVersion": c.get("unity", "6000.0.27f1"),
                              "fileCount": 3298, "totalBytes": 6781713784, "clientExecutableRelativePath": c.get("exe", "RecRoom.exe")},
                "externalLauncher": {"executablePath": launcher, "workingDirectory": str(Path(launcher).parent)} if launcher else None}
        cat["installations"].append(inst)
        Path(state).mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(json.dumps(cat), encoding="utf-8")
        tamper = load(pc / "tamper.json", [])
        if replace and iid in tamper:
            tamper.remove(iid)
            (pc / "tamper.json").write_text(json.dumps(tamper), encoding="utf-8")
        out(inst)

    def find(iid):
        if len(iid) != 32:
            err("invalid_id", "An installation ID must be a 32-character catalog identifier.")
        for i in cat["installations"]:
            if i["id"] == iid:
                return i
        err("installation_not_found", "No installation with that ID is in this catalog.")

    if cmd == "verify":
        inst = find(args[0])
        bad = inst["id"] in load(pc / "tamper.json", [])
        issues = [{"severity": "information", "code": "il2cpp_marker", "message": "IL2CPP layout.", "relativePath": None}]
        if bad:
            issues.append({"severity": "error", "code": "file_changed", "message": "A launch-related file no longer matches its imported SHA-256 fingerprint.", "relativePath": "GameAssembly.dll"})
        out({"installation": inst, "currentInventory": inst["inventory"], "issues": issues, "isValid": not bad}, 2 if bad else 0)
    if cmd in ("plan", "launch"):
        mode = take(args, "--mode") or "screen"
        target = take(args, "--target") or "client"
        approved = take(args, "--approved-launcher")
        inst = find(args[0])
        if inst["id"] in load(pc / "tamper.json", []):
            err("verification_failed", "Launch planning is blocked: A launch-related file no longer matches its imported SHA-256 fingerprint.")
        ext = inst.get("externalLauncher")
        if target == "external":
            if not ext:
                err("external_launcher_not_registered", "Explicitly register the intended external launcher during import first.")
            if approved != ext["executablePath"]:
                err("external_launcher_confirmation_required", "Supply the exact registered external launcher path as explicit launch input.")
            exe, wd, a = ext["executablePath"], ext["workingDirectory"], []
        else:
            if inst["inventory"]["externalModificationsDetected"]:
                err("external_launcher_required", "This installation contains external launcher or modification markers.")
            exe = inst["installRoot"] + "\\" + inst["inventory"]["clientExecutableRelativePath"]
            wd, a = inst["installRoot"], ["+forcemode:" + mode]
        plan = {"installationId": inst["id"], "installRoot": inst["installRoot"], "mode": mode, "target": "externalLauncher" if target == "external" else "client",
                "executablePath": exe, "workingDirectory": wd, "arguments": a, "canExecuteOnCurrentPlatform": True, "blockReason": None}
        if cmd == "plan":
            out(plan)
        if (pc / "launch.fail").exists():
            err("process_start_failed", "The operating system did not create the requested process.")
        pid = 4242
        if not (pc / "launch.nopid").exists():
            procs = load(pc / "procs.json", {})
            procs[str(pid)] = exe.rsplit("\\", 1)[-1].lower()
            (pc / "procs.json").write_text(json.dumps(procs), encoding="utf-8")
        out({"processId": pid, "startedAtUtc": "2026-10-26T12:00:00+00:00", "plan": plan})
    if cmd == "probe-backend":
        out({"reachable": True, "reason": "owned_backend_reachable", "serviceAddresses": 31, "gameLaunched": False})
    err("operation_failed", "Unknown command. Run 'help' for available commands.")


if __name__ == "__main__":
    main(sys.argv[1:])
